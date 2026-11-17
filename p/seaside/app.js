document.addEventListener("DOMContentLoaded", function () {
  var form = document.querySelector("form.form");
  if (!form) return;
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var ok = document.getElementById("ok");
    if (ok) ok.style.display = "block";
  });
});
