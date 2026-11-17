document.addEventListener("DOMContentLoaded", function () {
  var quiz = document.getElementById("quiz");
  var out = document.getElementById("result");
  if (!quiz || !out) return;
  var BOOK = "https://scheduler.servicetitan.com/book/eyJicmFuZElkIjoiYnJhbmRfY2J5eGYwNGoyYTZnbzJheHl4amt4dTF4Iiwic2NoZWR1bGVySWQiOiJzY2hlZF9wajJ4M2o2cDc2NDJjYjlub2lsYWh3am8ifQ==";

  quiz.addEventListener("submit", function (e) {
    e.preventDefault();
    var f = new FormData(quiz);
    var age = Number(f.get("age"));
    var sym = Number(f.get("sym"));
    var now = Number(f.get("now"));
    var title, body, cta, href;

    if (now === 1) {
      title = "Call now";
      body = "No heat or no cool is a same-day problem. Call the office and get on today's schedule.";
      cta = "Call 760-227-2828"; href = "tel:+17602272828";
    } else if (sym === 2) {
      title = "Get the free second opinion";
      body = "Before you sign a replacement quote, have Prestigious diagnose it. If it can be repaired, they'll say so.";
      cta = "Book a second opinion"; href = BOOK;
    } else if (age === 2 && sym === 1) {
      title = "Book a replacement consult";
      body = "An older system with repeat repairs is often worth comparing against a new one. You'll get both options explained.";
      cta = "Book a consult"; href = BOOK;
    } else {
      title = "Book a repair diagnosis";
      body = "This sounds fixable. Start with an honest diagnosis and a repair-first recommendation.";
      cta = "Book a diagnosis"; href = BOOK;
    }
    out.innerHTML = "<h4></h4><p></p><a class='btn btn-red'></a>";
    out.querySelector("h4").textContent = title;
    out.querySelector("p").textContent = body;
    var a = out.querySelector("a"); a.textContent = cta; a.href = href;
    out.style.display = "block";
  });
});
