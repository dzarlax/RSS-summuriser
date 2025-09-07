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
        from .extraction import ContentExtractor
        console.print(f"[cyan]Extracting:[/cyan] {url}")
        async with ContentExtractor() as extractor:
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


@cli.command()
@click.option('--limit', default=50, help='Maximum number of articles to process')
@click.option('--article-ids', help='Comma-separated list of specific article IDs')
@async_command
async def cache_media(limit: int, article_ids: str = None):
    """Cache media files for articles that have media but no cached files."""
    from .processing.media_cache_manager import MediaCacheManager
    from rich.progress import Progress, SpinnerColumn, TextColumn
    
    console.print("🎬 [bold blue]Media Caching Tool[/bold blue]")
    
    try:
        manager = MediaCacheManager()
        
        # Parse article IDs if provided
        target_article_ids = None
        if article_ids:
            try:
                target_article_ids = [int(id.strip()) for id in article_ids.split(',')]
                console.print(f"🎯 Targeting specific articles: {target_article_ids}")
            except ValueError:
                console.print("[red]❌ Invalid article IDs format. Use comma-separated integers.[/red]")
                return
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Caching media files...", total=None)
            
            stats = await manager.cache_media_for_articles(
                article_ids=target_article_ids,
                limit=limit
            )
            
            progress.update(task, description="✅ Media caching completed!")
        
        # Display results
        console.print("\n📊 [bold]Media Caching Results:[/bold]")
        console.print(f"  Articles processed: {stats['articles_processed']}")
        console.print(f"  Media cached: {stats['media_cached']}")
        console.print(f"  Media failed: {stats['media_failed']}")
        console.print(f"  Media skipped: {stats['media_skipped']}")
        
        if stats['errors']:
            console.print(f"\n❌ [red]{len(stats['errors'])} errors occurred:[/red]")
            for error in stats['errors'][:5]:  # Show first 5 errors
                console.print(f"  • {error}")
        
    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.option('--limit', default=50, help='Maximum number of articles to process')
@click.option('--dry-run', is_flag=True, help='Only show candidates without processing')
async def reprocess_failed(limit: int, dry_run: bool):
    """Find and reprocess articles where content extraction failed (title equals summary)."""
    orchestrator = NewsOrchestrator()
    
    try:
        await orchestrator.start()
        
        if dry_run:
            console.print(f"[bold yellow]🔍 Dry run: Finding articles with failed content extraction (limit: {limit})[/bold yellow]")
        else:
            console.print(f"[bold green]🔧 Reprocessing articles with failed content extraction (limit: {limit})[/bold green]")
        
        # Run the reprocessing
        results = await orchestrator.reprocess_failed_extractions(limit=limit, dry_run=dry_run)
        
        # Display results in a nice table
        console.print(f"\n[bold blue]📊 Results:[/bold blue]")
        
        # Summary table
        summary_table = Table()
        summary_table.add_column("Metric", style="cyan")
        summary_table.add_column("Value", style="white")
        
        summary_table.add_row("Found candidates", str(results['found_candidates']))
        if not dry_run:
            summary_table.add_row("Processed", str(results['processed']))
            summary_table.add_row("Improved", str(results['improved']))
            summary_table.add_row("Failed", str(results['failed']))
            summary_table.add_row("Success rate", f"{results['success_rate']:.1f}%")
            summary_table.add_row("Improvement rate", f"{results['improvement_rate']:.1f}%")
        
        console.print(summary_table)
        
        # Show improvements if any
        if not dry_run and results.get('improvements'):
            console.print(f"\n[bold green]✅ Articles with improved content:[/bold green]")
            
            improvements_table = Table()
            improvements_table.add_column("ID", style="cyan")
            improvements_table.add_column("Title", style="white", max_width=50)
            improvements_table.add_column("Original", style="red")
            improvements_table.add_column("New", style="green")
            improvements_table.add_column("Improvement", style="yellow")
            
            for improvement in results['improvements'][:10]:  # Show top 10
                improvements_table.add_row(
                    str(improvement['article_id']),
                    improvement['title'],
                    f"{improvement['original_length']} chars",
                    f"{improvement['new_length']} chars",
                    f"+{improvement['improvement']} (+{improvement['percentage']:.1f}%)"
                )
            
            console.print(improvements_table)
            
            if len(results['improvements']) > 10:
                console.print(f"[dim]... and {len(results['improvements']) - 10} more improvements[/dim]")
        
        # Show candidates in dry run mode
        if dry_run and results.get('candidates'):
            console.print(f"\n[bold yellow]🎯 Reprocessing candidates:[/bold yellow]")
            
            candidates_table = Table()
            candidates_table.add_column("ID", style="cyan")
            candidates_table.add_column("Title", style="white", max_width=50)
            candidates_table.add_column("Domain", style="blue")
            candidates_table.add_column("Content", style="red")
            
            for candidate in results['candidates'][:15]:  # Show top 15
                candidates_table.add_row(
                    str(candidate['id']),
                    candidate['title'],
                    candidate['domain'],
                    f"{candidate['content_length']} chars"
                )
            
            console.print(candidates_table)
            
            if len(results['candidates']) > 15:
                console.print(f"[dim]... and {len(results['candidates']) - 15} more candidates[/dim]")
            
            console.print(f"\n[bold yellow]💡 Run without --dry-run to process these articles[/bold yellow]")
        
        # Show errors if any
        if not dry_run and results.get('errors'):
            console.print(f"\n[bold red]❌ Processing errors:[/bold red]")
            
            for error in results['errors'][:5]:  # Show first 5 errors
                console.print(f"   Article {error['article_id']}: {error['error']}")
            
            if len(results['errors']) > 5:
                console.print(f"   [dim]... and {len(results['errors']) - 5} more errors[/dim]")
        
    except Exception as e:
        console.print(f"[bold red]❌ Error during reprocessing: {e}[/bold red]")
        raise
    finally:
        await orchestrator.stop()


@cli.command()
@click.argument('ai_category')
@click.argument('new_fixed_category')
@click.option('--description', help='Description for the mapping change')
async def update_mapping(ai_category: str, new_fixed_category: str, description: str):
    """Update a category mapping and apply changes to existing articles."""
    try:
        from .services.category_service import CategoryService
        
        async with AsyncSessionLocal() as db:
            service = CategoryService(db)
            
            # Validate fixed category
            if new_fixed_category not in service.ALLOWED_CATEGORIES:
                console.print(f"[red]❌ Invalid fixed category: {new_fixed_category}[/red]")
                console.print(f"[yellow]Allowed categories: {list(service.ALLOWED_CATEGORIES.keys())}[/yellow]")
                sys.exit(1)
            
            console.print(f"[cyan]🔄 Updating mapping: {ai_category} → {new_fixed_category}[/cyan]")
            
            # Apply the mapping change
            success = await service.update_category_mapping(
                ai_category=ai_category,
                new_fixed_category=new_fixed_category,
                description=description or f"CLI update: {ai_category} → {new_fixed_category}"
            )
            
            if success:
                console.print(f"[green]✅ Successfully updated mapping and applied to existing articles[/green]")
            else:
                console.print(f"[red]❌ Failed to update mapping[/red]")
                sys.exit(1)
    
    except Exception as e:
        console.print(f"[red]❌ Error updating mapping: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.option('--limit', '-l', default=50, help='Maximum number of articles to process')
@click.option('--article-ids', help='Comma-separated list of article IDs to cache')
async def cache_media(limit: int, article_ids: Optional[str]):
    """Cache media files for articles."""
    from .processing.media_cache_manager import MediaCacheManager
    
    article_id_list = None
    if article_ids:
        try:
            article_id_list = [int(x.strip()) for x in article_ids.split(',')]
            console.print(f"[bold blue]📸 Caching media for specific articles: {article_id_list}[/bold blue]")
        except ValueError:
            console.print("[red]❌ Invalid article IDs format. Use comma-separated integers.[/red]")
            sys.exit(1)
    else:
        console.print(f"[bold blue]📸 Caching media for up to {limit} articles with uncached media[/bold blue]")
    
    try:
        media_cache_manager = MediaCacheManager()
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Caching media files...", total=None)
            
            if article_id_list:
                stats = await media_cache_manager.cache_media_for_articles(article_ids=article_id_list, limit=limit)
            else:
                stats = await media_cache_manager.cache_media_for_articles(limit=limit)
            
            progress.remove_task(task)
        
        # Display results
        console.print(f"\n[bold green]✅ Media caching completed![/bold green]")
        console.print(f"• Articles processed: {stats['articles_processed']}")
        console.print(f"• Media files cached: {stats['media_cached']}")
        console.print(f"• Media files failed: {stats['media_failed']}")
        console.print(f"• Media files skipped: {stats['media_skipped']}")
        
        if stats['errors']:
            console.print(f"\n[bold red]Errors ({len(stats['errors'])}):[/bold red]")
            for error in stats['errors'][:5]:  # Show first 5 errors
                console.print(f"• {error}")
            if len(stats['errors']) > 5:
                console.print(f"... and {len(stats['errors']) - 5} more errors")
    
    except Exception as e:
        console.print(f"[red]❌ Media caching failed: {e}[/red]")
        sys.exit(1)


@cli.command()
async def cache_stats():
    """Show media cache statistics."""
    from .services.media_cache_service import get_media_cache_service
    
    try:
        media_cache_service = get_media_cache_service()
        stats = await media_cache_service.get_cache_stats()
        
        if 'error' in stats:
            console.print(f"[red]❌ Error getting cache stats: {stats['error']}[/red]")
            sys.exit(1)
        
        console.print(f"[bold blue]📊 Media Cache Statistics:[/bold blue]")
        console.print(f"• Cache directory: {stats['cache_dir']}")
        console.print(f"• Total files: {stats['total_files']}")
        console.print(f"• Total size: {stats['total_size_mb']} MB")
        
        # Show by type
        if stats['by_type']:
            console.print(f"\n[bold]By media type:[/bold]")
            table = Table()
            table.add_column("Type")
            table.add_column("Files", justify="right")
            table.add_column("Size (MB)", justify="right")
            table.add_column("Original", justify="right")
            table.add_column("Thumbnails", justify="right")
            table.add_column("Optimized", justify="right")
            
            for media_type, type_stats in stats['by_type'].items():
                size_mb = round(type_stats['size_bytes'] / (1024 * 1024), 2)
                
                # Variant counts
                original = type_stats['by_variant'].get('original', {}).get('files', 0)
                thumbnails = type_stats['by_variant'].get('thumbnails', {}).get('files', 0)
                optimized = type_stats['by_variant'].get('optimized', {}).get('files', 0)
                
                table.add_row(
                    media_type.title(),
                    str(type_stats['files']),
                    str(size_mb),
                    str(original),
                    str(thumbnails),
                    str(optimized)
                )
            
            console.print(table)
    
    except Exception as e:
        console.print(f"[red]❌ Error getting cache stats: {e}[/red]")
        sys.exit(1)


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
reprocess_failed = async_command(reprocess_failed)
update_mapping = async_command(update_mapping)
cache_media = async_command(cache_media)
cache_stats = async_command(cache_stats)


if __name__ == '__main__':
    cli()