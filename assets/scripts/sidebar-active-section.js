<script>
document.addEventListener("DOMContentLoaded", () => {
  const sidebar = document.querySelector("#quarto-sidebar");
  if (!sidebar) return;

  const activeLink = sidebar.querySelector("a.sidebar-link.active");
  if (!activeLink) return;

  // Start with the immediate section containing the active page
  let topSection = activeLink.closest("li.sidebar-item-section");
  if (!topSection) return;

  // Climb to the outermost section, e.g. Delivery -> Teaching
  while (true) {
    const parentSection = topSection.parentElement?.closest(
      "li.sidebar-item-section"
    );

    if (!parentSection || !sidebar.contains(parentSection)) {
      break;
    }

    topSection = parentSection;
  }

  // Expand all subsections within the active top-level section
  topSection.querySelectorAll(".collapse").forEach((element) => {
    element.classList.add("show");
  });

  // Synchronize arrows and accessibility state
  topSection
    .querySelectorAll('[data-bs-toggle="collapse"]')
    .forEach((toggle) => {
      toggle.classList.remove("collapsed");
      toggle.setAttribute("aria-expanded", "true");
    });
});
</script>