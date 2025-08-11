"""Command line interface for RSS Summarizer v2."""

import asyncio
import sys
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from .orchestrator import NewsOrchestrator
from .services.source_manager import SourceManager
from .database import AsyncSessionLocal
from .config import settings


console = Console()


def async_command(f):
    """Decorator to run async CLI commands."""
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapper


@click.group()
@click.version_option(version="2.0.0")
def cli():
    """RSS Summarizer v2 - Modern news aggregator."""
    pass


@cli.command()
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def process(verbose: bool):
    """Run the main news processing cycle."""
    async def _process():
        orchestrator = NewsOrchestrator()
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            
            task = progress.add_task("Processing news...", total=None)
            
            try:
                stats = await orchestrator.run_full_cycle()
                progress.update(task, description="✅ Processing completed!")
            
                # Display results
                console.print("\n[bold green]Processing Summary:[/bold green]")
                console.print(f"• Articles fetched: {stats['articles_fetched']}")
                console.print(f"• Articles processed: {stats['articles_processed']}")
                console.print(f"• Clusters created: {stats['clusters_created']}")
                console.print(f"• Clusters updated: {stats['clusters_updated']}")
                console.print(f"• API calls made: {stats['api_calls_made']}")
                console.print(f"• Duration: {stats.get('duration_seconds', 0):.1f}s")
                
                if stats['errors']:
                    console.print(f"\n[bold yellow]Errors ({len(stats['errors'])}):[/bold yellow]")
                    for error in stats['errors'][:5]:  # Show first 5 errors
                        console.print(f"• {error}")
                    if len(stats['errors']) > 5:
                        console.print(f"• ... and {len(stats['errors']) - 5} more")
                
            except Exception as e:
                progress.update(task, description="❌ Processing failed!")
                console.print(f"\n[bold red]Error:[/bold red] {e}")
                sys.exit(1)
    
    # Run the async function
    asyncio.run(_process())


@cli.command()
@click.option('--url', required=True, help='Article URL to extract')
@async_command
async def extract_url(url: str):
    """Extract article content and metadata from a single URL."""
    try:
        from .services.content_extractor import get_content_extractor
        extractor = await get_content_extractor()
        console.print(f"[cyan]Extracting:[/cyan] {url}")
        result = await extractor.extract_article_content_with_metadata(url)
        content = result.get('content')
        pub_date = result.get('publication_date')
        full_url = result.get('full_article_url')
        # Print short summary
        preview = (content[:400] + '...') if content and len(content) > 400 else (content or '')
        table = Table(title="Extraction Result")
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        table.add_row("Publication Date", str(pub_date))
        table.add_row("Full Article URL", str(full_url))
        table.add_row("Content Preview", preview)
        console.print(table)
    except Exception as e:
        console.print(f"[red]❌ Extraction failed:[/red] {e}")
        sys.exit(1)


@cli.command()
@async_command
async def sources():
    """Manage news sources."""
    source_manager = SourceManager()
    
    async with AsyncSessionLocal() as db:
        sources_list = await source_manager.get_sources(db)
        
        if not sources_list:
            console.print("[yellow]No sources configured.[/yellow]")
            return
        
        # Create table
        table = Table(title="News Sources")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="bold")
        table.add_column("Type", style="magenta")
        table.add_column("Status", style="green")
        table.add_column("Last Fetch", style="dim")
        table.add_column("Errors", style="red")
        
        for source in sources_list:
            status = "✅ Enabled" if source.enabled else "❌ Disabled"
            last_fetch = source.last_fetch.strftime("%Y-%m-%d %H:%M") if source.last_fetch else "Never"
            errors = str(source.error_count) if source.error_count > 0 else "-"
            
            table.add_row(
                str(source.id),
                source.name,
                source.source_type,
                status,
                last_fetch,
                errors
            )
        
        console.print(table)


@cli.command()
@click.argument('name')
@click.argument('source_type', type=click.Choice(['rss', 'telegram', 'reddit', 'twitter']))
@click.argument('url')
async def add_source(name: str, source_type: str, url: str):
    """Add a new news source."""
    source_manager = SourceManager()
    
    try:
        async with AsyncSessionLocal() as db:
            source = await source_manager.create_source(db, name, source_type, url)
            
            if source.enabled:
                console.print(f"[green]✅ Added source '{name}' successfully![/green]")
            else:
                console.print(f"[yellow]⚠️ Added source '{name}' but connection test failed.[/yellow]")
                console.print(f"Error: {source.last_error}")
    
    except Exception as e:
        console.print(f"[red]❌ Failed to add source: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument('source_id', type=int)
async def test_source(source_id: int):
    """Test connection to a source."""
    source_manager = SourceManager()
    
    try:
        async with AsyncSessionLocal() as db:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task(f"Testing source {source_id}...", total=None)
                
                is_connected = await source_manager.test_source_connection(db, source_id)
                
                if is_connected:
                    progress.update(task, description="✅ Connection successful!")
                    console.print(f"[green]Source {source_id} is working correctly.[/green]")
                else:
                    progress.update(task, description="❌ Connection failed!")
                    console.print(f"[red]Source {source_id} connection failed.[/red]")
    
    except Exception as e:
        console.print(f"[red]❌ Error testing source: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.option('--days', '-d', default=7, help='Number of days to show stats for')
async def stats(days: int):
    """Show processing statistics."""
    orchestrator = NewsOrchestrator()
    
    try:
        stats_data = await orchestrator.get_processing_stats(days)
        
        # Show totals
        totals = stats_data['totals']
        console.print(f"[bold blue]Statistics for last {days} days:[/bold blue]")
        console.print(f"• Articles fetched: {totals['articles_fetched']}")
        console.print(f"• Articles processed: {totals['articles_processed']}")
        console.print(f"• Clusters created: {totals['clusters_created']}")
        console.print(f"• API calls made: {totals['api_calls_made']}")
        console.print(f"• Total processing time: {totals['total_processing_time']}s")
        
        if totals['errors_count'] > 0:
            console.print(f"• [red]Errors: {totals['errors_count']}[/red]")
        
        # Show daily breakdown
        if stats_data['daily_stats']:
            console.print(f"\n[bold]Daily breakdown:[/bold]")
            table = Table()
            table.add_column("Date")
            table.add_column("Articles", justify="right")
            table.add_column("Clusters", justify="right")
            table.add_column("API Calls", justify="right")
            table.add_column("Errors", justify="right", style="red")
            
            for day_stat in stats_data['daily_stats'][:10]:  # Show last 10 days
                table.add_row(
                    day_stat['date'],
                    str(day_stat['articles_fetched']),
                    str(day_stat['clusters_created']),
                    str(day_stat['api_calls_made']),
                    str(day_stat['errors_count']) if day_stat['errors_count'] > 0 else "-"
                )
            
            console.print(table)
    
    except Exception as e:
        console.print(f"[red]❌ Error getting stats: {e}[/red]")
        sys.exit(1)


@cli.command()
async def config():
    """Show current configuration."""
    console.print("[bold blue]RSS Summarizer v2 Configuration:[/bold blue]")
    
    # Show key settings (without secrets)
    table = Table()
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="white")
    
    config_items = [
        ("Database URL", settings.database_url),
        ("Redis URL", settings.redis_url),
        ("API Endpoint", str(settings.api_endpoint) if settings.api_endpoint else "Not configured"),
        ("API Rate Limit", f"{settings.api_rate_limit} req/sec"),
        ("Log Level", settings.log_level),
        ("Max Workers", str(settings.max_workers)),
        ("Cache TTL", f"{settings.cache_ttl}s"),
        ("Cache Directory", settings.cache_dir),
        ("Development Mode", "Yes" if settings.development else "No"),
    ]
    
    for key, value in config_items:
        # Hide sensitive values
        if "token" in key.lower() or "secret" in key.lower() or "password" in key.lower():
            value = "***hidden***" if value else "Not configured"
        
        table.add_row(key, str(value))
    
    console.print(table)


# Async command support
def async_command(f):
    """Decorator to support async click commands."""
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapper


# Apply async decorator to all async commands
process = async_command(process)
sources = async_command(sources)
add_source = async_command(add_source)
test_source = async_command(test_source)
stats = async_command(stats)
config = async_command(config)


if __name__ == '__main__':
    cli()