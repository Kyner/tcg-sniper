// Aplica o tema salvo antes de pintar a página (mesma chave "tema" do admin antigo). Fica num arquivo (e não
// inline no index.html) para a Content-Security-Policy do Caddy poder proibir scripts inline.
try {
  var t = localStorage.getItem("tema");
  if (t === "winter" || t === "night") document.documentElement.dataset.theme = t;
} catch (e) {}
