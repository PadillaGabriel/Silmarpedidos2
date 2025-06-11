// static/scanner.js

// — Sonido de aviso —
const beep = new Audio('/static/beep.mp3');

// — Vídeo & canvas para capturar frames —
const videoEl  = document.createElement('video');
const canvasEl = document.createElement('canvas');
const ctx      = canvasEl.getContext('2d');

// — Estilos y atributos del vídeo —
Object.assign(videoEl, {
  autoplay: true,
  muted: true,
  playsInline: true,
  disablePictureInPicture: true,
  disableRemotePlayback: true,
});
videoEl.setAttribute('webkit-playsinline', '');
videoEl.style.cssText = `
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  box-sizing: border-box;
  aspect-ratio: 1/1;
`;

// ocultamos el canvas (solo sirve para capturar imagen)
canvasEl.style.display = 'none';

// insertamos en el contenedor #reader
const container = document.getElementById('reader');
container.style.position = 'relative';
container.append(videoEl, canvasEl);

let scanInterval;

// — Inicializa la cámara (elige trasera si hay) —
async function iniciarCamara() {
  const devices = await navigator.mediaDevices.enumerateDevices();
  const back = devices.find(d =>
    d.kind === 'videoinput' && /back|rear|environment/i.test(d.label)
  );
  const constraints = back
    ? { deviceId: { exact: back.deviceId } }
    : { facingMode: 'environment' };

  const stream = await navigator.mediaDevices.getUserMedia({
    video: { ...constraints, width: { ideal: 640 }, height: { ideal: 480 } }
  });
  videoEl.srcObject = stream;
  await videoEl.play();
}

// — Envía un frame al servidor para decodificar el QR —
async function escanearFrame() {
  if (!videoEl.videoWidth) return;

  canvasEl.width  = videoEl.videoWidth;
  canvasEl.height = videoEl.videoHeight;
  ctx.drawImage(videoEl, 0, 0);

  canvasEl.toBlob(async blob => {
    const form = new FormData();
    form.append('frame', blob, 'frame.jpg');

    try {
      const res = await fetch('/decode-qr', {
        method: 'POST',
        body: form,
        credentials: 'include'
      });
      if (!res.ok) return;
      const json = await res.json();
      console.log('decode-qr:', json);

      if (json.error) {
        // mostramos error al usuario
        alert(json.error);
        return;
      }

      if (json.data && json.data.shipment_id) {
        // efecto visual
        videoEl.style.outline = '5px solid lime';
        setTimeout(() => videoEl.style.outline = '', 500);
        // sonido
        beep.play().catch(() => {});
        // llamamos a tu lógica con el shipment_id
        escanear(json.data.shipment_id);
        detenerEscaneo();
      }
    } catch (e) {
      console.error('decode-qr error:', e);
    }
  }, 'image/jpeg');
}


// — Detiene el escaneo (parar intervalos y cámara) —
function detenerEscaneo() {
  clearInterval(scanInterval);
  videoEl.srcObject?.getTracks().forEach(t => t.stop());
  document.getElementById('stop-btn').disabled = true;
}

// — Lógica para manejar el ID encontrado o ingresado —
async function escanear(id) {
  // Ejemplo: llama a tu endpoint que devuelve detalle de pedido
  const res = await fetch(`/api/pedidos/${id}`, { credentials: 'include' });
  if (!res.ok) return;
  const data = await res.json();
  mostrarDetalle(data);
}

// — Muestra el detalle en el DOM —
function mostrarDetalle(data) {
  document.getElementById('cliente').textContent = data.cliente;
  const tbody = document.getElementById('tabla-items');
  tbody.innerHTML = '';
  data.items.forEach(item => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><img src="${item.imagen}" width="50"></td>
      <td>${item.titulo}</td>
      <td>${item.sku}</td>
      <td>${item.variante}</td>
      <td>${item.cantidad}</td>
    `;
    tbody.append(tr);
  });
  document.getElementById('detalle-pedido').style.display = 'block';
  document.getElementById('boton-armar').style.display = 'block';
}

// — Al cargar la página —
document.addEventListener('DOMContentLoaded', () => {
  // arrancamos la cámara y el intervalo
  iniciarCamara().catch(e => console.error('Cámara:', e));
  scanInterval = setInterval(escanearFrame, 800);

  // botón detener
  const stopBtn = document.getElementById('stop-btn');
  stopBtn.onclick = detenerEscaneo;

  // subir imagen de QR
  document.getElementById('input-escanear').onchange = async e => {
    const file = e.target.files[0];
    if (!file) return;
    const form = new FormData();
    form.append('frame', file, file.name);
    try {
      const res = await fetch('/decode-qr', {
        method: 'POST',
        body: form,
        credentials: 'include'
      });
      const json = await res.json();
      if (json.data) escanear(json.data);
    } catch (err) {
      console.error('decode-qr imagen:', err);
    }
  };

  // ingreso manual de ID
  document.getElementById('btn-manual').onclick = () => {
    const id = document.getElementById('manual-id').value.trim();
    if (id) escanear(id);
  };
});
