(function() {
          // Canvas: wcagCompareChart
const wcagCtx = document.getElementById('wcagCompareChart');
if (wcagCtx) {
  const wcagChart = new Chart(wcagCtx, {
    type: 'bar',
    data: {
      labels: ['Semantic Structure', 'ARIA Support', 'Keyboard Nav', 'Screen-Reader Compat', 'Auto Color-Contrast'],
      datasets: [
        {
          label: 'HTML Slides',
          data: [95, 98, 92, 95, 85],
          backgroundColor: '#0F766E',
          borderColor: '#115E59',
          borderWidth: 1,
          borderRadius: 4,
          barPercentage: 0.7,
          categoryPercentage: 0.7
        },
        {
          label: 'PowerPoint',
          data: [40, 15, 50, 55, 60],
          backgroundColor: '#4B5563',
          borderColor: '#374151',
          borderWidth: 1,
          borderRadius: 4,
          barPercentage: 0.7,
          categoryPercentage: 0.7
        }
      ]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          beginAtZero: true,
          max: 100,
          ticks: {
            callback: function(value) { return value + '%'; },
            font: { family: '"Inter", "Helvetica Neue", Arial, sans-serif', size: 12 },
            color: '#4B5563'
          },
          grid: {
            color: '#E2E8F0'
          },
          title: {
            display: true,
            text: 'Native WCAG 2.1 AA Coverage',
            font: { family: '"Inter", "Helvetica Neue", Arial, sans-serif', size: 13, weight: '600' },
            color: '#374151'
          }
        },
        y: {
          ticks: {
            font: { family: '"Inter", "Helvetica Neue", Arial, sans-serif', size: 13 },
            color: '#374151'
          },
          grid: {
            display: false
          }
        }
      },
      plugins: {
        legend: {
          position: 'top',
          align: 'start',
          labels: {
            boxWidth: 14,
            boxHeight: 14,
            borderRadius: 3,
            useBorderRadius: true,
            padding: 16,
            font: { family: '"Inter", "Helvetica Neue", Arial, sans-serif', size: 13, weight: '600' },
            color: '#111827'
          }
        },
        tooltip: {
          callbacks: {
            label: function(context) {
              return context.dataset.label + ': ' + context.parsed.x + '%';
            }
          }
        }
      }
    }
  });
}
        })();
