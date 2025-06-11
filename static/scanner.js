// static/scanner.js

// —– Configuración de sonido y elementos HTML —–
const beep     = new Audio('/static/beep.mp3');
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

// oculto el canvas porque sólo lo uso para capturar
canvasEl.style.display = 'none';

// lo inserto en el contenedor
const reader = document.getElementById('reader');
reader.style.position = 'relative';
reader.append(videoEl, canvasEl);

let scanning = false;      // evita solapar peticiones
let finished = false;      // marca que ya escaneamos

// —– Función para arrancar la cámara trasera —–
async function iniciarCamara() {
  const devices = await navigator.mediaDevices.enumerateDevices();
  const back = devices.find(d =>
    d.kind === 'videoinput' && /back|rear|environment/i.test(d.label)
  );
  const constraintVideo = back
    ? { deviceId: { exact: back.deviceId } }
    : { facingMode: 'environment' };
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { ...constraintVideo, width:{ideal:640}, height:{ideal:480} }
  });
  videoEl.srcObject = stream;
  await videoEl.play();
}

// —– Función que captura un frame y, si hay QR, llama al backend —–
async function escanearFrame() {
  if (finished || scanning || !videoEl.videoWidth) return;

  scanning = true;
  // preparo el canvas al tamaño real del vídeo
  canvasEl.width  = videoEl.videoWidth;
  canvasEl.height = videoEl.videoHeight;
  ctx.drawImage(videoEl, 0, 0);

  // convierto a blob y envío
  canvasEl.toBlob(async blob => {
    try {
      const form = new FormData();
      form.append('frame', blob, 'frame.jpg');

      const res = await fetch('/decode-qr', {
        method: 'POST',
        body: form,
        credentials: 'include'
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();

      if (json.data) {
        // ¡QR DETECTADO!
        finished = true;

        // feedback visual
        videoEl.style.outline = '5px solid lime';
        setTimeout(() => videoEl.style.outline = '', 500);

        // feedback sonoro
        beep.play().catch(() => {});

        // tu lógica de negocio: mostramos detalle
        mostrarDetalle(json.detalle);
      }
    } catch (e) {
      console.error('Error enviando la imagen', e);
      document.getElementById('error-msg').textContent = 'Error al enviar la imagen';
    } finally {
      scanning = false;
    }
  }, 'image/jpeg');
}

// —– Loop de escaneo automático —–
function startAutoScan() {
  // cada 500 ms intentamos
  setInterval(escanearFrame, 500);
}

// —– Tu función para pintar el detalle en la página —–
function mostrarDetalle(detalle) {
  // Ejemplo muy simplificado. Completa según tu HTML:
  document.getElementById('detalle-pedido').style.display = 'block';
  document.getElementById('cliente').textContent = detalle.cliente;
  const tbody = document.getElementById('tabla-items');
  tbody.innerHTML = detalle.items.map(i => `
    <tr>
      <td><img src="${i.imagenes[0].thumbnail}" width="50"></td>
      <td>${i.titulo}</td>
      <td>${i.sku}</td>
      <td>${i.variante}</td>
      <td>${i.cantidad}</td>
    </tr>
  `).join('');
  document.getElementById('boton-armar').style.display = 'block';
}

// —– Iniciamos todo al cargar DOM —–
document.addEventListener('DOMContentLoaded', async () => {
  try {
    await iniciarCamara();
    startAutoScan();
  } catch (e) {
    console.error('No se pudo acceder a la cámara:', e);
    document.getElementById('error-msg').textContent = 'No se pudo acceder a la cámara';
  }

  // botón “Detener cámara”
  document.getElementById('stop-btn').onclick = () => {
    videoEl.srcObject?.getTracks().forEach(t => t.stop());
  };
});
