// RSS Summarizer v2 JavaScript - Enhanced Admin Interface

// Простая функция для AJAX запросов (make it global)
async function apiRequest(url, options = {}) {
    try {
        const response = await fetch(url, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        return await response.json();
    } catch (error) {
        console.error('API request failed:', error);
        throw error;
    }
}

// Global NewsAggregator object
window.NewsAggregator = {
    apiRequest: apiRequest,
    showNotification: null, // Will be set after initialization
    showLoading: null,
    hideLoading: null,
    validateForm: null,
    animateNumber: null
};

document.addEventListener('DOMContentLoaded', function() {
    console.log('RSS Summarizer v2 Enhanced Admin loaded');
    
    // Initialize admin interface enhancements
    initAdminEnhancements();
    
    // Enhanced admin interface functionality
    function initAdminEnhancements() {
        // Add smooth scrolling
        addSmoothScrolling();
        
        // Enhance stats cards with animations
        enhanceStatsCards();
        
        // Add interactive tooltips
        addTooltips();
        
        // Enhance buttons with ripple effects
        enhanceButtons();
        
        // Initialize notification system
        initNotifications();
        
        // Add keyboard shortcuts
        addKeyboardShortcuts();
    }
    
    // Smooth scrolling for navigation links
    function addSmoothScrolling() {
        document.querySelectorAll('a[href^="#"]').forEach(anchor => {
            anchor.addEventListener('click', function (e) {
                e.preventDefault();
                const target = document.querySelector(this.getAttribute('href'));
                if (target) {
                    target.scrollIntoView({
                        behavior: 'smooth',
                        block: 'start'
                    });
                }
            });
        });
    }
    
    // Enhance stats cards with hover animations and click effects
    function enhanceStatsCards() {
        const statCards = document.querySelectorAll('.stat-card');
        
        statCards.forEach(card => {
            card.addEventListener('mouseenter', function() {
                this.style.transform = 'translateY(-8px) scale(1.02)';
            });
            
            card.addEventListener('mouseleave', function() {
                this.style.transform = 'translateY(0) scale(1)';
            });
            
            // Add click animation
            card.addEventListener('click', function() {
                this.style.transform = 'translateY(-4px) scale(0.98)';
                setTimeout(() => {
                    this.style.transform = 'translateY(-8px) scale(1.02)';
                }, 150);
            });
        });
    }
    
    // Add tooltips for better UX
    function addTooltips() {
        const elementsWithTooltips = document.querySelectorAll('[data-tooltip]');
        
        elementsWithTooltips.forEach(element => {
            const tooltip = document.createElement('div');
            tooltip.className = 'tooltip';
            tooltip.textContent = element.dataset.tooltip;
            document.body.appendChild(tooltip);
            
            element.addEventListener('mouseenter', function(e) {
                tooltip.style.display = 'block';
                updateTooltipPosition(e, tooltip);
            });
            
            element.addEventListener('mousemove', function(e) {
                updateTooltipPosition(e, tooltip);
            });
            
            element.addEventListener('mouseleave', function() {
                tooltip.style.display = 'none';
            });
        });
    }
    
    function updateTooltipPosition(e, tooltip) {
        tooltip.style.left = e.pageX + 10 + 'px';
        tooltip.style.top = e.pageY - 30 + 'px';
    }
    
    // Enhance buttons with ripple effects
    function enhanceButtons() {
        const buttons = document.querySelectorAll('.btn, button');
        
        buttons.forEach(button => {
            button.addEventListener('click', function(e) {
                const ripple = document.createElement('span');
                const rect = this.getBoundingClientRect();
                const size = Math.max(rect.width, rect.height);
                const x = e.clientX - rect.left - size / 2;
                const y = e.clientY - rect.top - size / 2;
                
                ripple.style.width = ripple.style.height = size + 'px';
                ripple.style.left = x + 'px';
                ripple.style.top = y + 'px';
                ripple.classList.add('ripple');
                
                this.appendChild(ripple);
                
                setTimeout(() => {
                    ripple.remove();
                }, 600);
            });
        });
    }
    
    // Notification system
    function initNotifications() {
        const notificationContainer = document.createElement('div');
        notificationContainer.id = 'notification-container';
        notificationContainer.className = 'notification-container';
        document.body.appendChild(notificationContainer);
    }
    
    function showNotification(message, type = 'info', duration = 5000) {
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.innerHTML = `
            <div class="notification-content">
                <span class="notification-icon">${getNotificationIcon(type)}</span>
                <span class="notification-message">${message}</span>
                <button class="notification-close">&times;</button>
            </div>
        `;
        
        const container = document.getElementById('notification-container');
        container.appendChild(notification);
        
        // Auto-remove notification
        setTimeout(() => {
            removeNotification(notification);
        }, duration);
        
        // Close button functionality
        notification.querySelector('.notification-close').addEventListener('click', () => {
            removeNotification(notification);
        });
        
        // Add entrance animation
        setTimeout(() => {
            notification.classList.add('notification-show');
        }, 100);
    }
    
    function removeNotification(notification) {
        notification.classList.add('notification-hide');
        setTimeout(() => {
            if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
            }
        }, 300);
    }
    
    function getNotificationIcon(type) {
        const icons = {
            success: '✅',
            error: '❌',
            warning: '⚠️',
            info: 'ℹ️'
        };
        return icons[type] || icons.info;
    }
    
    // Keyboard shortcuts
    function addKeyboardShortcuts() {
        document.addEventListener('keydown', function(e) {
            // Ctrl/Cmd + D for dashboard
            if ((e.ctrlKey || e.metaKey) && e.key === 'd') {
                e.preventDefault();
                window.location.href = '/admin';
            }
            
            // Ctrl/Cmd + S for sources
            if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                e.preventDefault();
                window.location.href = '/admin/sources';
            }
            
            // Ctrl/Cmd + R for refresh current page
            if ((e.ctrlKey || e.metaKey) && e.key === 'r') {
                e.preventDefault();
                location.reload();
            }
        });
    }
    
    // Enhanced loading states
    function showLoading(element, text = 'Загрузка...') {
        element.innerHTML = `
            <div class="loading-enhanced">
                <div class="loading-spinner"></div>
                <span>${text}</span>
            </div>
        `;
    }
    
    function hideLoading(element, content) {
        element.innerHTML = content;
    }
    
    // Form validation helpers
    function validateForm(formElement) {
        const inputs = formElement.querySelectorAll('input, textarea, select');
        let isValid = true;
        
        inputs.forEach(input => {
            if (input.hasAttribute('required') && !input.value.trim()) {
                showInputError(input, 'Это поле обязательно для заполнения');
                isValid = false;
            } else {
                hideInputError(input);
            }
        });
        
        return isValid;
    }
    
    function showInputError(input, message) {
        input.classList.add('input-error');
        let errorElement = input.parentNode.querySelector('.input-error-message');
        
        if (!errorElement) {
            errorElement = document.createElement('div');
            errorElement.className = 'input-error-message';
            input.parentNode.appendChild(errorElement);
        }
        
        errorElement.textContent = message;
    }
    
    function hideInputError(input) {
        input.classList.remove('input-error');
        const errorElement = input.parentNode.querySelector('.input-error-message');
        if (errorElement) {
            errorElement.remove();
        }
    }
    
    // Animate numbers (for stats)
    function animateNumber(element, endValue, duration = 1000) {
        const startValue = 0;
        const startTime = performance.now();
        
        function updateNumber(currentTime) {
            const elapsedTime = currentTime - startTime;
            const progress = Math.min(elapsedTime / duration, 1);
            const currentValue = Math.floor(startValue + (endValue - startValue) * progress);
            
            element.textContent = currentValue.toLocaleString();
            
            if (progress < 1) {
                requestAnimationFrame(updateNumber);
            }
        }
        
        requestAnimationFrame(updateNumber);
    }
    
    // Update global NewsAggregator with initialized functions
    window.NewsAggregator.showNotification = showNotification;
    window.NewsAggregator.showLoading = showLoading;
    window.NewsAggregator.hideLoading = hideLoading;
    window.NewsAggregator.validateForm = validateForm;
    window.NewsAggregator.animateNumber = animateNumber;
    
    // Add CSS for new components
    addEnhancementStyles();
});

// Add dynamic styles for enhancements
function addEnhancementStyles() {
    const style = document.createElement('style');
    style.textContent = `
        /* Tooltip styles */
        .tooltip {
            position: absolute;
            background: rgba(0, 0, 0, 0.9);
            color: white;
            padding: 0.5rem 1rem;
            border-radius: 0.375rem;
            font-size: 0.875rem;
            pointer-events: none;
            z-index: 1000;
            display: none;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        
        /* Ripple effect */
        .ripple {
            position: absolute;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.3);
            transform: scale(0);
            animation: ripple-animation 0.6s linear;
            pointer-events: none;
        }
        
        @keyframes ripple-animation {
            to {
                transform: scale(4);
                opacity: 0;
            }
        }
        
        /* Notification styles */
        .notification-container {
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 1000;
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }
        
        .notification {
            background: white;
            border-radius: 0.75rem;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
            border: 1px solid var(--border-color);
            min-width: 300px;
            transform: translateX(100%);
            transition: transform 0.3s ease;
        }
        
        .notification-show {
            transform: translateX(0);
        }
        
        .notification-hide {
            transform: translateX(100%);
        }
        
        .notification-content {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            padding: 1rem;
        }
        
        .notification-icon {
            font-size: 1.25rem;
        }
        
        .notification-message {
            flex: 1;
            font-weight: 500;
        }
        
        .notification-close {
            background: none;
            border: none;
            font-size: 1.25rem;
            cursor: pointer;
            color: var(--text-muted);
        }
        
        .notification-close:hover {
            color: var(--text-color);
        }
        
        .notification-success {
            border-left: 4px solid var(--success-color);
        }
        
        .notification-error {
            border-left: 4px solid var(--danger-color);
        }
        
        .notification-warning {
            border-left: 4px solid var(--warning-color);
        }
        
        .notification-info {
            border-left: 4px solid var(--info-color);
        }
        
        /* Enhanced loading */
        .loading-enhanced {
            display: flex;
            align-items: center;
            gap: 1rem;
            justify-content: center;
            padding: 2rem;
        }
        
        .loading-spinner {
            width: 24px;
            height: 24px;
            border: 3px solid var(--border-color);
            border-top-color: var(--primary-color);
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        
        /* Form error styles */
        .input-error {
            border-color: var(--danger-color) !important;
            box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.1) !important;
        }
        
        .input-error-message {
            color: var(--danger-color);
            font-size: 0.875rem;
            margin-top: 0.25rem;
            font-weight: 500;
        }
        
        /* Button loading state */
        .btn-loading {
            pointer-events: none;
            opacity: 0.7;
        }
        
        .btn-loading::after {
            content: '';
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 2px solid currentColor;
            border-right-color: transparent;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin-left: 0.5rem;
        }
    `;
    
    document.head.appendChild(style);
}