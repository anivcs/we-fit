// Both can be overridden per device with ?api=...&controller=... so the same build
// works on any display machine on the local network.
const params = new URLSearchParams(window.location.search);

export const API_BASE_URL = (
  params.get('api') ||
  import.meta.env.VITE_API_BASE_URL ||
  `${window.location.protocol}//${window.location.hostname}:8000/api/v1`
).replace(/\/+$/, '');

export const CONTROLLER_URL = params.get('controller') || import.meta.env.VITE_CONTROLLER_URL || '';
