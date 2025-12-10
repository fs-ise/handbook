<script>
document.addEventListener("DOMContentLoaded", function () {
  const today = new Date();
  const dayIndex = today.getDay(); // 0 = Sunday, 6 = Saturday
  const weekdays = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  const dayName = weekdays[dayIndex];

  const isWeekend = (dayIndex === 0 || dayIndex === 6);

  // Current mode according to Quarto (based on body class)
  const isCurrentlyDark = document.body.classList.contains("quarto-dark");

  // If it's weekend and we're not already dark, ask Quarto to toggle
  if (isWeekend && !isCurrentlyDark && window.quartoToggleColorScheme) {
    window.quartoToggleColorScheme();
    console.log(`Today is ${dayName}. Weekend detected → switched to dark mode via Quarto toggle.`);
  } else {
    console.log(
      `Today is ${dayName}. isWeekend=${isWeekend}, isCurrentlyDark=${isCurrentlyDark}. No automatic switch.`
    );
  }
});
</script>
