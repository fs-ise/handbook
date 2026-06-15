<script>
document.addEventListener("DOMContentLoaded", () => {
  const sidebar = document.querySelector("#quarto-sidebar");
  if (!sidebar) return;
  
  const activeLink = sidebar.querySelector("a.sidebar-link.active");
  if (!activeLink) return;
  
  // Find the top-level sidebar section that contains the active page
  const topSection = activeLink.closest("li.sidebar-item-section");
  if (!topSection) return;
  
  // Expand all nested collapsible sections inside the active top-level section
  topSection.querySelectorAll(".collapse").forEach((el) => {
    el.classList.add("show");
  });
  
  // Update toggle buttons/arrows so their visual state matches
  topSection.querySelectorAll('[data-bs-toggle="collapse"]').forEach((toggle) => {
    toggle.classList.remove("collapsed");
    toggle.setAttribute("aria-expanded", "true");
  });
});
</script>