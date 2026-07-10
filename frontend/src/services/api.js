// =============================================================================
// FILE   : src/services/api.js
// WHAT   : the ONE axios instance that the whole frontend uses to hit Flask.
// WHY    : so we don't repeat the baseURL + "Authorization: Bearer <token>"
//          header in every single API call. Configure once, use everywhere.
// USED BY: literally every other service file ->
//            services/auth.js     (login / register / me)
//            services/admin.js    (admin CRUD + M7 job triggers)
//            services/company.js  (jobs, applications, placements)
//            services/student.js  (profile, jobs, applications, placements)
//            services/exports.js  (M7 async CSV export + polling)
// =============================================================================

import axios from 'axios'

// baseURL is '/api' (NOT http://localhost:5000/api) on purpose.
// vite.config.js has a dev proxy that forwards /api -> Flask on :5000.
// keeps us CORS-free in dev + means prod just works if both are same-origin.
const api = axios.create({
  baseURL: '/api',
})

// -----------------------------------------------------------------------------
// REQUEST INTERCEPTOR
// what : runs before EVERY outgoing request, no exceptions.
// job  : grab the JWT out of localStorage and slap it on the Authorization
//        header so the backend's @token_required / @role_required decorators
//        (see backend/auth_utils.py) let us through.
// why localStorage and not a JS variable?
//        -> survives a page refresh (F5). a plain variable would be wiped and
//           the user would get logged out every reload.
// note : if there's no token (logged out / login page) we just skip it and the
//        backend replies 401, which is what we want.
// -----------------------------------------------------------------------------
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export default api
