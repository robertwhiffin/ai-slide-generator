(function() {
          // Canvas: deviceRenderChart
const deviceCtx = document.getElementById('deviceRenderChart');
if (deviceCtx) {
  new Chart(deviceCtx, {
    type: 'bar',
    data: {
      labels: ['Laptop', 'Tablet', 'Phone', 'Projector'],
      datasets: [
        {
          label: 'HTML Slides',
          data: [100, 100, 100, 100],
          backgroundColor: '#0F766E',
          borderRadius: 6,
          barPercentage: 0.7,
          categoryPercentage: 0.6
        },
        {
          label: 'PowerPoint (.pptx)',
          data: [95, 60, 35, 70],
          backgroundColor: '#B91C1C',
          borderRadius: 6,
          barPercentage: 0.7,
          categoryPercentage: 0.6
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: {
          beginAtZero: true,
          max: 100,
          ticks: {
            callback: function(value) { return value + '%'; },
            font: { family: '"Inter", "Helvetica Neue", Arial, sans-serif', size: 12 },
            color: '#4B5563'
          },
          title: {
            display: true,
            text: 'Rendering fidelity',
            font: { family: '"Inter", "Helvetica Neue", Arial, sans-serif', size: 13, weight: '600' },
            color: '#374151'
          },
          grid: { color: '#E2E8F0' }
        },
        x: {
          ticks: {
            font: { family: '"Inter", "Helvetica Neue", Arial, sans-serif', size: 13 },
            color: '#374151'
          },
          grid: { display: false }
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
            font: { family: '"Inter", "Helvetica Neue", Arial, sans-serif', size: 13 },
            color: '#374151'
          }
        },
        tooltip: {
          callbacks: {
            label: function(context) {
              return context.dataset.label + ': ' + context.parsed.y + '% fidelity';
            }
          }
        }
      }
    }
  });
}
        })();
