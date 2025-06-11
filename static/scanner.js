// static/scanner.js
// ——————————————
// Variables globales
const beep       = new Audio('/static/beep.mp3');
const videoEl    = document.createElement('video');
const canvasEl   = document.createElement('canvas');
const ctx        = canvasEl.getContext('2d');
const errorMsgEl = document.getElementById('error-msg');

async function iniciarCamara() {
  const devices = await navigator.mediaDevices.enumerateDevices();
  const back = devices.find(d =>
    d.kind === 'videoinput' && /back|rear|environment/i.test(d.label)
  );
  const constraintVideo = back
    ? { deviceId: { exact: back.deviceId } }
    : { facingMode: 'environment' };

  const stream = await navigator.mediaDevices.getUserMedia({
    video: { ...constraintVideo, width:{ ideal:640 }, height:{ ideal:480 } }
  });

  videoEl.srcObject = stream;
  await videoEl.play();
}

async function escanearFrame() {
  errorMsgEl.textContent = '';        // limpio mensajes previos
  if (!videoEl.videoWidth) {
    errorMsgEl.textContent = 'La cámara aún no está lista.';
    return;
  }

  // Capturo un frame
  canvasEl.width  = videoEl.videoWidth;
  canvasEl.height = videoEl.videoHeight;
  ctx.drawImage(videoEl, 0, 0);

  // Lo envío al servidor como 'frame'
  canvasEl.toBlob(async blob => {
    const form = new FormData();
    form.append('frame', blob, 'frame.jpg');  // el nombre 'frame' coincide con tu FastAPI

    try {
      const res = await fetch('/decode-qr', {
        method: 'POST',
        body: form,
        credentials: 'include'
      });

      if (!res.ok) {
        // 422, 400, etc. -> trato de leer JSON de error
        let msg = `HTTP ${res.status}`;
        try {
          const j = await res.json();
          if (j.error) msg = j.error;
        } catch {}
        throw new Error(msg);
      }

      const json = await res.json();

      if (!json.data) {
        throw new Error(json.error || 'QR no detectado');
      }

      // aviso visual y sonoro
      videoEl.style.outline = '5px solid lime';
      setTimeout(() => videoEl.style.outline = '', 500);
      beep.play().catch(() => {});

      // llamo a tu lógica de negocio
      escanear(json.data);

    } catch (e) {
      console.error('Error enviando la imagen:', e);
      errorMsgEl.textContent = `Error enviando la imagen: ${e.message}`;
    }
  }, 'image/jpeg');
}

document.addEventListener('DOMContentLoaded', () => {
  // Preparo el video y canvas dentro de #reader
  const container = document.getElementById('reader');
  container.style.position = 'relative';

  Object.assign(videoEl.style, {
    display:        'block',
    width:          '100%',
    height:         '100%',
    objectFit:      'cover',
    boxSizing:      'border-box',
    aspectRatio:    '1/1'
  });
  videoEl.autoplay                = true;
  videoEl.muted                   = true;
  videoEl.playsInline             = true;
  videoEl.disablePictureInPicture = true;
  videoEl.disableRemotePlayback   = true;
  videoEl.setAttribute('playsinline',       '');
  videoEl.setAttribute('webkit-playsinline', '');

  canvasEl.style.display = 'none';
  container.append(videoEl, canvasEl);

  // Botones
  document.getElementById('scan-btn')
          .addEventListener('click', escanearFrame);

  document.getElementById('stop-btn')
          .addEventListener('click', () => {
            videoEl.srcObject?.getTracks().forEach(t => t.stop());
          });

  // Arranco la cámara
  iniciarCamara().catch(e => {
    console.error('Cámara:', e);
    errorMsgEl.textContent = `No se pudo abrir la cámara: ${e.message}`;
  });
});
