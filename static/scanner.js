// static/scanner.js

// Sonido de aviso
const beep = new Audio('/static/beep.mp3');

// Creamos video y canvas
const videoEl  = document.createElement('video');
const canvasEl = document.createElement('canvas');
const ctx      = canvasEl.getContext('2d');

// Configuración vídeo
videoEl.autoplay                = true;
videoEl.muted                   = true;
videoEl.playsInline             = true;
videoEl.disablePictureInPicture = true;
videoEl.setAttribute('playsinline','');
videoEl.style.cssText = `
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  box-sizing: border-box;
  aspect-ratio: 1/1;
`;

// Canvas oculto
canvasEl.style.display = 'none';

// Insertamos en el contenedor
const container = document.getElementById('reader');
container.style.position = 'relative';
container.append(videoEl, canvasEl);

// Arranca la cámara tras cargar DOM
async function iniciarCamara() {
  try {
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
  } catch (e) {
    document.getElementById('error-msg').textContent = 'No se pudo iniciar la cámara';
    console.error(e);
  }
}

// Extrae datos del QR de un blob
async function escanearFrame() {
  if (!videoEl.videoWidth) {
    document.getElementById('error-msg').textContent = 'La cámara no está lista';
    return;
  }

  canvasEl.width  = videoEl.videoWidth;
  canvasEl.height = videoEl.videoHeight;
  ctx.drawImage(videoEl, 0, 0);

  canvasEl.toBlob(async blob => {
    const form = new FormData();
    form.append('frame', blob, 'frame.jpg');

    const res = await fetch('/decode-qr', {
      method: 'POST',
      body: form,
      credentials: 'include'
    });

    if (!res.ok) {
      document.getElementById('error-msg').textContent = 'Error al procesar imagen';
      console.warn('HTTP', res.status);
      return;
    }

    const json = await res.json();

    if (json.error || !json.data) {
      // QR no detectado o inválido
      document.getElementById('error-msg').textContent = json.error || 'QR no detectado';
      videoEl.style.outline = '5px solid crimson';
      setTimeout(() => videoEl.style.outline = '', 500);
      return;
    }

    // QR ok!
    document.getElementById('error-msg').textContent = '';
    videoEl.style.outline = '5px solid lime';
    setTimeout(() => videoEl.style.outline = '', 500);

    // Sonido
    beep.play().catch(() => {});

    // Renderiza detalle (tendrás que implementar mostrarDetalle)
    mostrarDetalle(json.detalle);
  }, 'image/jpeg');
}

document.addEventListener('DOMContentLoaded', () => {
  iniciarCamara();

  document.getElementById('scan-btn').onclick = () => {
    escanearFrame().catch(e => {
      document.getElementById('error-msg').textContent = 'Error inesperado';
      console.error(e);
    });
  };

  document.getElementById('stop-btn').onclick = () => {
    videoEl.srcObject?.getTracks().forEach(t => t.stop());
  };
});
