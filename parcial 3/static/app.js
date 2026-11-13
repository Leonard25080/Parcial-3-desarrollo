for (const boton of document.querySelectorAll('[data-open]')) {
    boton.addEventListener('click', () => {
        const ventana = document.getElementById(boton.dataset.open);
        if (ventana) ventana.classList.add('visible');
    });
}
for (const boton of document.querySelectorAll('[data-close]')) {
    boton.addEventListener('click', () => boton.closest('.modal').classList.remove('visible'));
}
for (const ventana of document.querySelectorAll('.modal')) {
    ventana.addEventListener('click', evento => {
        if (evento.target === ventana) ventana.classList.remove('visible');
    });
}
document.addEventListener('keydown', evento => {
    if (evento.key === 'Escape') {
        document.querySelectorAll('.modal.visible').forEach(ventana => ventana.classList.remove('visible'));
    }
});
// Pedir confirmación antes de eliminar o autorizar movimientos
for (const formulario of document.querySelectorAll('form[data-confirm]')) {
    formulario.addEventListener('submit', evento => {
        if (!confirm(formulario.dataset.confirm)) evento.preventDefault();
    });
}