document.addEventListener("DOMContentLoaded", function () {
  var cards = document.querySelectorAll(".fix-card");
  var form = document.getElementById("request");
  var picked = document.getElementById("picked");
  var issue = document.getElementById("issue");

  cards.forEach(function (card) {
    card.setAttribute("aria-pressed", "false");
    card.addEventListener("click", function () {
      cards.forEach(function (c) { c.setAttribute("aria-pressed", "false"); });
      card.setAttribute("aria-pressed", "true");
      var label = card.dataset.issue + " (" + card.dataset.trade + ")";
      picked.textContent = label;
      issue.value = label;
      form.hidden = false;
      form.scrollIntoView({ behavior: "smooth", block: "nearest" });
      var first = form.querySelector("input[name=name]");
      if (first) first.focus({ preventScroll: true });
    });
  });

  if (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      document.getElementById("ok").style.display = "block";
    });
  }
});
