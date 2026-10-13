/* Comportamiento de la interfaz (funciona también sin JavaScript, solo mejora la experiencia). */
(function () {
  "use strict";

  // ---------------------------------------------------------- confirmación al eliminar
  var dialogo = document.getElementById("dialogo-confirmar");
  document.addEventListener("submit", function (e) {
    var form = e.target;
    var mensaje = form.getAttribute("data-confirm");
    if (!mensaje || form.dataset.confirmado) return;
    e.preventDefault();

    if (!dialogo || typeof dialogo.showModal !== "function") {
      if (window.confirm(mensaje)) { form.dataset.confirmado = "1"; form.submit(); }
      return;
    }
    dialogo.querySelector("#dialogo-mensaje").textContent = mensaje;
    var botonAceptar = dialogo.querySelector("button[value=aceptar]");
    botonAceptar.textContent = form.getAttribute("data-confirm-texto") || "Sí, eliminar";
    dialogo.returnValue = "";
    dialogo.showModal();
    dialogo.addEventListener("close", function alCerrar() {
      dialogo.removeEventListener("close", alCerrar);
      if (dialogo.returnValue === "aceptar") {
        form.dataset.confirmado = "1";
        form.submit();
      }
    });
  });

  // Cerrar el diálogo al hacer clic fuera.
  if (dialogo) {
    dialogo.addEventListener("click", function (e) {
      if (e.target === dialogo) dialogo.close("cancelar");
    });
  }

  // ---------------------------------------------------------- mensajes
  document.querySelectorAll(".flashes .flash").forEach(function (flash) {
    var cerrar = function () {
      flash.classList.add("saliendo");
      setTimeout(function () { flash.remove(); }, 300);
    };
    var boton = flash.querySelector(".flash-close");
    if (boton) boton.addEventListener("click", cerrar);
    if (flash.classList.contains("flash-ok")) setTimeout(cerrar, 5000);
  });

  // ---------------------------------------------------------- formulario de movimiento
  var formMov = document.querySelector("[data-form-movimiento]");
  if (formMov) {
    var selectCat = formMov.querySelector("[data-categorias]");
    var filtrarCategorias = function () {
      var marcado = formMov.querySelector("input[name=tipo]:checked");
      var tipo = marcado ? marcado.value : null;
      var visibles = [];
      Array.prototype.forEach.call(selectCat.options, function (op) {
        if (!op.value) return;
        var valida = !tipo || op.dataset.tipo === "ambos" || op.dataset.tipo === tipo;
        op.hidden = !valida;
        op.disabled = !valida;
        if (valida) visibles.push(op);
      });
      var actual = selectCat.selectedOptions[0];
      if (actual && actual.value && actual.disabled) selectCat.value = "";
      if (!selectCat.value && visibles.length === 1) selectCat.value = visibles[0].value;
    };
    formMov.querySelectorAll("input[name=tipo]").forEach(function (r) {
      r.addEventListener("change", filtrarCategorias);
    });
    filtrarCategorias();

    // Evita envíos dobles.
    formMov.addEventListener("submit", function (e) {
      if (formMov.dataset.enviando) { e.preventDefault(); return; }
      formMov.dataset.enviando = "1";
      setTimeout(function () { delete formMov.dataset.enviando; }, 4000);
    });
  }

  // ---------------------------------------------------------- filtros de movimientos
  var periodo = document.querySelector("[data-periodo]");
  if (periodo) {
    var personalizados = document.querySelectorAll("[data-personalizado]");
    var actualizar = function () {
      var mostrar = periodo.value === "personalizado";
      personalizados.forEach(function (campo) {
        campo.hidden = !mostrar;
        campo.querySelector("input").disabled = !mostrar;
      });
    };
    periodo.addEventListener("change", function () {
      actualizar();
      if (periodo.value !== "personalizado") periodo.form.submit();
    });
    document.querySelectorAll("#filtros select:not([data-periodo])").forEach(function (s) {
      s.addEventListener("change", function () { s.form.submit(); });
    });
    actualizar();
  }

  // ---------------------------------------------------------- informes
  document.querySelectorAll("[data-autosubmit]").forEach(function (campo) {
    campo.addEventListener("change", function () { if (campo.value) campo.form.submit(); });
  });
  document.querySelectorAll("[data-imprimir]").forEach(function (b) {
    b.addEventListener("click", function () { window.print(); });
  });
})();
