// static/scanner.js

// — Elementos y configuraciones —
const readerEl   = document.getElementById('reader');
const scanBtn    = document.getElementById('scan-btn');
const stopBtn    = document.getElementById('stop-btn');
const errorMsgEl = document.getElementById('error-msg');

// Creamos video + canvas
const videoEl  = document.createElement('video');
const canvasEl = document.createElement('canvas');
const ctx      = canvasEl.getContext('2d');

videoEl.autoplay                = true;
videoEl.muted                   = true;
videoEl.playsInline             = true;
videoEl.disablePictureInPicture = true;
videoEl.style.cssText = `
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  box-sizing: border-box;
  aspect-ratio: 1/1;
`;

// ocultar canvas
canvasEl.style.display = 'none';

// añadir al contenedor
readerEl.style.position = 'relative';
readerEl.append(videoEl, canvasEl);

// — Función para iniciar la cámara —
async function iniciarCamara() {
  const devices = await navigator.mediaDevices.enumerateDevices();
  const back = devices.find(d =>
    d.kind === 'videoinput' && /back|rear|environment/i.test(d.label)
  );
  const constraints = back
    ? { deviceId: { exact: back.deviceId } }
    : { facingMode: 'environment' };

  const stream = await navigator.mediaDevices.getUserMedia({
    video: { ...constraints, width:{ideal:640}, height:{ideal:480} }
  });
  videoEl.srcObject = stream;
  await videoEl.play();
}

// — Función para mostrar en pantalla el detalle recibido —
function mostrarDetalle(detalle) {
  // aquí iría tu lógica: poblar tabla, mostrar #detalle-pedido…
  // por ejemplo:
  document.getElementById('cliente').textContent = detalle.cliente;
  const tbody = document.getElementById('tabla-items');
  tbody.innerHTML = '';
  detalle.items.forEach(i => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><img src="${i.imagenes[0].thumbnail}" width="50"></td>
      <td>${i.titulo}</td>
      <td>${i.sku}</td>
      <td>${i.variante}</td>
      <td>${i.cantidad}</td>
    `;
    tbody.append(tr);
  });
  document.getElementById('detalle-pedido').style.display = 'block';
}

// — Evento de “Escanear QR” —
scanBtn.addEventListener('click', () => {
  errorMsgEl.textContent = '';
  if (!videoEl.videoWidth) {
    errorMsgEl.textContent = 'La cámara aún no está lista';
    return;
  }

  // dibujar un único frame
  canvasEl.width  = videoEl.videoWidth;
  canvasEl.height = videoEl.videoHeight;
  ctx.drawImage(videoEl, 0, 0, canvasEl.width, canvasEl.height);

  canvasEl.toBlob(async blob => {
    const form = new FormData();
    form.append('frame', blob, 'snapshot.jpg'); // ¡CAMPO 'frame'!

    try {
      const res = await fetch('/decode-qr', {
        method: 'POST',
        body: form,
        credentials: 'include'
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();

      if (json.error || !json.data) {
        errorMsgEl.textContent = json.error || 'QR no detectado';
        videoEl.style.outline = '5px solid crimson';
        setTimeout(() => videoEl.style.outline = '', 500);
      } else {
        videoEl.style.outline = '5px solid lime';
        setTimeout(() => videoEl.style.outline = '', 500);
        mostrarDetalle(json.detalle);
      }
    } catch (e) {
      console.error(e);
      errorMsgEl.textContent = 'Error enviando la imagen';
    }
  }, 'image/jpeg');
});

// — Evento “Detener cámara” —
stopBtn.addEventListener('click', () => {
  videoEl.srcObject?.getTracks().forEach(t => t.stop());
});

// — Al cargar DOM, arrancar la cámara —
document.addEventListener('DOMContentLoaded', () => {
  iniciarCamara().catch(e => {
    console.error('Cámara:', e);
    errorMsgEl.textContent = 'No fue posible acceder a la cámara';
  });
});
