import axios from 'axios';

const BASE = import.meta.env.VITE_API_URL || '';

const api = axios.create({ baseURL: BASE, timeout: 10000 });

export const getStats       = ()            => api.get('/api/stats');
export const getEvents      = (status)      => api.get('/api/events', { params: status ? { status } : {} });
export const getEvent       = (id)          => api.get(`/api/events/${id}`);
export const getApprovals   = ()            => api.get('/api/approvals');
export const approveFix     = (fixId, body) => api.post(`/api/approvals/${fixId}/approve`, body);
export const denyFix        = (fixId, body) => api.post(`/api/approvals/${fixId}/deny`, body);
export const submitEvent    = (payload)     => api.post('/api/pipeline-event', payload);
