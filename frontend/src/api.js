import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export const getPartners = (filter = 'all', search = '', tag = '') =>
  api.get('/partners', { params: { filter, search, tag } }).then(r => r.data)

export const getPartner = (index) =>
  api.get(`/partners/${index}`).then(r => r.data)

export const updatePartner = (index, data) =>
  api.patch(`/partners/${index}`, data).then(r => r.data)

export const getStats = () =>
  api.get('/stats').then(r => r.data)

export const getActivity = () =>
  api.get('/activity').then(r => r.data)

export const addContact = (index, contact) =>
  api.post(`/partners/${index}/contacts`, contact).then(r => r.data)

export const removeContact = (index, contactIndex) =>
  api.delete(`/partners/${index}/contacts/${contactIndex}`).then(r => r.data)

export const sendReply = (index, body) =>
  api.post(`/partners/${index}/reply`, { body }).then(r => r.data)

export const scanInbox = () =>
  api.post('/scan').then(r => r.data)

export const sendBatch = () =>
  api.post('/send_batch').then(r => r.data)

export const retryBatch = () =>
  api.post('/retry_batch').then(r => r.data)

export const sendThankyou = () =>
  api.post('/send_thankyou').then(r => r.data)

export const sendKeepwarm = () =>
  api.post('/send_keepwarm').then(r => r.data)

export const archiveNoResponse = (days = 30) =>
  api.post('/archive_no_response', { days }).then(r => r.data)

export const takeSnapshot = () =>
  api.post('/snapshot').then(r => r.data)

export const exportCsv = () =>
  window.open('/api/export', '_blank')
