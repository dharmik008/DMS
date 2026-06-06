// Caryanams DMS - Main JavaScript

// Sidebar Toggle
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    if (sidebar) {
        sidebar.classList.toggle('open');
    }
}

// Close sidebar on click outside (mobile)
document.addEventListener('click', function(event) {
    const sidebar = document.getElementById('sidebar');
    const toggleBtn = document.querySelector('.sidebar-toggle');
    
    if (window.innerWidth <= 768 && sidebar && sidebar.classList.contains('open')) {
        if (!sidebar.contains(event.target) && !toggleBtn?.contains(event.target)) {
            sidebar.classList.remove('open');
        }
    }
});

// Current Date Display
function updateCurrentDate() {
    const dateElement = document.getElementById('currentDate');
    if (dateElement) {
        const now = new Date();
        const options = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
        dateElement.textContent = now.toLocaleDateString('en-IN', options);
    }
}

// EMI Calculator Function
function calculateEMI() {
    const principal = parseFloat(document.getElementById('emi_principal')?.value);
    const rate = parseFloat(document.getElementById('emi_rate')?.value);
    const months = parseFloat(document.getElementById('emi_months')?.value);
    const resultDiv = document.getElementById('emi_result');
    
    if (!resultDiv) return;
    
    if (principal && rate && months && principal > 0 && rate > 0 && months > 0) {
        const monthlyRate = rate / (12 * 100);
        const emi = (principal * monthlyRate * Math.pow(1 + monthlyRate, months)) / (Math.pow(1 + monthlyRate, months) - 1);
        
        const totalPayment = emi * months;
        const totalInterest = totalPayment - principal;
        
        resultDiv.innerHTML = `
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;text-align:center">
                <div>
                    <div style="font-size:11px;color:var(--text-secondary)">Monthly EMI</div>
                    <div style="font-family:'Syne',sans-serif;font-size:20px;font-weight:800;color:var(--navy)">₹${Math.round(emi).toLocaleString('en-IN')}</div>
                </div>
                <div>
                    <div style="font-size:11px;color:var(--text-secondary)">Total Interest</div>
                    <div style="font-family:'Syne',sans-serif;font-size:16px;font-weight:700;color:var(--warning)">₹${Math.round(totalInterest).toLocaleString('en-IN')}</div>
                </div>
                <div>
                    <div style="font-size:11px;color:var(--text-secondary)">Total Payment</div>
                    <div style="font-family:'Syne',sans-serif;font-size:16px;font-weight:700;color:var(--success)">₹${Math.round(totalPayment).toLocaleString('en-IN')}</div>
                </div>
            </div>
        `;
    } else {
        resultDiv.innerHTML = '<p style="font-size:13px;color:var(--text-muted)">Enter loan amount, interest rate, and tenure to calculate EMI</p>';
    }
}

// Lead Follow-up Date Validation
function validateFollowUpDate(inputElement) {
    if (!inputElement) return true;
    
    const selectedDate = new Date(inputElement.value);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    
    if (selectedDate <= today) {
        alert('Follow-up date must be a future date (tomorrow or later)');
        inputElement.value = '';
        return false;
    }
    return true;
}

// Set min date for follow-up picker to tomorrow
function setFollowUpMinDate() {
    const followUpInput = document.querySelector('input[name="follow_up_date"]');
    if (followUpInput) {
        const tomorrow = new Date();
        tomorrow.setDate(tomorrow.getDate() + 1);
        tomorrow.setHours(0, 0, 0, 0);
        const minDate = tomorrow.toISOString().slice(0, 16);
        followUpInput.setAttribute('min', minDate);
        
        // Add validation on change
        followUpInput.addEventListener('change', function() {
            validateFollowUpDate(this);
        });
    }
}

// Delete Confirmation
function confirmDelete(formId, message) {
    if (confirm(message || 'Are you sure you want to delete this item? This action cannot be undone.')) {
        document.getElementById(formId).submit();
    }
}

// Print Invoice
function printInvoice() {
    window.print();
}

// Chart.js for Dashboard (if available)
function initCharts() {
    const leadDataElement = document.getElementById('leadData');
    if (leadDataElement && typeof Chart !== 'undefined') {
        try {
            const leadData = JSON.parse(leadDataElement.textContent);
            const ctx = document.getElementById('leadChart')?.getContext('2d');
            if (ctx) {
                new Chart(ctx, {
                    type: 'bar',
                    data: {
                        labels: ['New', 'Contacted', 'Interested', 'Test Drive', 'Negotiation', 'Converted'],
                        datasets: [{
                            label: 'Leads',
                            data: leadData,
                            backgroundColor: '#DAA520',
                            borderRadius: 6
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: true
                    }
                });
            }
        } catch(e) {
            console.log('Chart data not available');
        }
    }
    
    // Revenue Chart
    const revenueLabels = document.getElementById('revenueLabels');
    const revenueValues = document.getElementById('revenueValues');
    if (revenueLabels && revenueValues && typeof Chart !== 'undefined') {
        try {
            const labels = JSON.parse(revenueLabels.textContent);
            const values = JSON.parse(revenueValues.textContent);
            const ctx = document.getElementById('revenueChart')?.getContext('2d');
            if (ctx) {
                new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'Revenue (₹)',
                            data: values,
                            borderColor: '#DAA520',
                            backgroundColor: 'rgba(218, 165, 32, 0.1)',
                            fill: true,
                            tension: 0.4
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: true,
                        plugins: {
                            legend: { position: 'bottom' }
                        }
                    }
                });
            }
        } catch(e) {
            console.log('Revenue chart data not available');
        }
    }
}

// Auto-hide flash messages
function autoHideFlashMessages() {
    const flashes = document.querySelectorAll('.flash, .flash-bar');
    flashes.forEach(flash => {
        setTimeout(() => {
            flash.style.opacity = '0';
            setTimeout(() => {
                if (flash.parentElement) flash.remove();
            }, 300);
        }, 5000);
    });
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    updateCurrentDate();
    setFollowUpMinDate();
    initCharts();
    autoHideFlashMessages();
    
    // Add active class to current nav item
    const currentPath = window.location.pathname;
    document.querySelectorAll('.nav-item, .nav-links a').forEach(link => {
        if (link.getAttribute('href') === currentPath) {
            link.classList.add('active');
        }
    });
});

// Export for global use
window.confirmDelete = confirmDelete;
window.toggleSidebar = toggleSidebar;
window.printInvoice = printInvoice;
window.calculateEMI = calculateEMI;
window.validateFollowUpDate = validateFollowUpDate;