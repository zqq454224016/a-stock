/**
 * 页面导航、筛选逻辑
 */

(function () {
  const searchInput = document.getElementById('search-input');
  const categoryFilter = document.getElementById('category-filter');

  if (!searchInput && !categoryFilter) return;

  function filterReports() {
    const keyword = (searchInput?.value || '').trim().toLowerCase();
    const category = categoryFilter?.value || 'all';

    document.querySelectorAll('.report-section').forEach(section => {
      const listCategory = section.querySelector('.report-list')?.dataset.category;
      const sectionMatch = category === 'all' || listCategory === category;
      section.style.display = sectionMatch ? '' : 'none';

      if (!sectionMatch) return;

      section.querySelectorAll('.report-item:not(.empty-hint)').forEach(item => {
        const name = (item.dataset.name || item.textContent || '').toLowerCase();
        const match = !keyword || name.includes(keyword);
        item.classList.toggle('hidden', !match);
      });
    });
  }

  searchInput?.addEventListener('input', filterReports);
  categoryFilter?.addEventListener('change', filterReports);

  // 锚点平滑滚动偏移
  if (window.location.hash) {
    const target = document.querySelector(window.location.hash);
    if (target) {
      setTimeout(() => target.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100);
    }
  }
})();
