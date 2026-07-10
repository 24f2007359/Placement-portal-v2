// =============================================================================
// FILE   : src/services/auth.js
// WHAT   : the auth "store" -> holds who is logged in + the JWT, and exposes
//          login / register / logout helpers.
// WHY    : router guards, the navbar, and every dashboard all need to know
//          "who am i and what's my role". one shared reactive blob = no prop
//          drilling, no re-fetching /auth/me on every component.
// USED BY:
//   App.vue                    -> navbar (show email/role) + logout button
//   router/index.js            -> beforeEach guard (isAuthenticated + role check)
//   views/LoginView.vue        -> auth.login()
//   views/RegisterStudentView  -> auth.registerStudent()
//   views/RegisterCompanyView  -> auth.registerCompany()
//   views/StudentDashboard.vue -> auth.user?.profile?.full_name
//   views/CompanyDashboard.vue -> auth.user?.profile?.name
//
// BACKEND COUNTERPART: backend/routes.py  (auth_bp, url_prefix=/api/auth)
// =============================================================================

import { reactive } from 'vue'
import api from './api'

// -----------------------------------------------------------------------------
// the single source of truth. reactive() so vue re-renders when it changes.
//
// we bootstrap it FROM localStorage (not empty) -> that's what keeps you logged
// in across a hard refresh. JSON.parse('null') === null, hence the '|| null'
// fallback string, otherwise JSON.parse(undefined) would explode.
// -----------------------------------------------------------------------------
const state = reactive({
  token: localStorage.getItem('token'),
  user: JSON.parse(localStorage.getItem('user') || 'null'),
})

/**
 * useAuth()
 * what : composable -> call it anywhere to get at the auth state + actions.
 * gotcha: `state` lives OUTSIDE this function on purpose. so every component
 *         that calls useAuth() shares the SAME object. if we declared state
 *         inside, each component would get its own copy = broken.
 */
export function useAuth() {
  /**
   * setSession(token, user)
   * what : after a successful login/register, save the JWT + user everywhere.
   * where: called by login(), registerStudent(), registerCompany() below.
   * why localStorage too? -> api.js interceptor reads the token from there on
   *      every request, and we re-hydrate `state` from there on page load.
   */
  function setSession(token, user) {
    state.token = token
    state.user = user
    localStorage.setItem('token', token)
    localStorage.setItem('user', JSON.stringify(user))
  }

  /**
   * logout()
   * what : nuke the session -> memory + localStorage both.
   * where: App.vue navbar Logout button.
   * note : purely client-side. JWTs are stateless, backend has no session to
   *        kill. the token technically stays valid till it expires (24h, see
   *        Config.JWT_EXPIRATION_HOURS) -- we just throw our copy away.
   */
  function logout() {
    state.token = null
    state.user = null
    localStorage.removeItem('token')
    localStorage.removeItem('user')
  }

  /**
   * login(email, password) -> POST /api/auth/login
   * what : hand creds to Flask, it verifies the password hash, hands back
   *        { token, user, redirect }.
   * where: views/LoginView.vue -> handleLogin()
   * returns: the whole `data` blob, because LoginView needs data.redirect to
   *          know WHICH dashboard to push() to (admin/company/student).
   * throws : axios throws on 4xx. LoginView catches and shows err.response.data.error
   *          e.g. "Invalid email or password", "Account is deactivated".
   */
  async function login(email, password) {
    const { data } = await api.post('/auth/login', { email, password })
    setSession(data.token, data.user)
    return data
  }

  /**
   * registerStudent(form) -> POST /api/auth/register/student
   * what : student self-signup. backend makes a User(role=student) + Student row.
   * where: views/RegisterStudentView.vue
   * note : student is logged in IMMEDIATELY (backend returns a token). no admin
   *        approval needed -- unlike companies.
   */
  async function registerStudent(form) {
    const { data } = await api.post('/auth/register/student', form)
    setSession(data.token, data.user)
    return data
  }

  /**
   * registerCompany(form) -> POST /api/auth/register/company
   * what : company signup. creates User(role=company) + Company row with
   *        approval_status = PENDING.
   * where: views/RegisterCompanyView.vue
   * gotcha: they DO get a token + land on /company/dashboard, but the dashboard
   *         API returns 403 until an admin approves them. CompanyDashboard.vue
   *         catches that 403 and shows the "awaiting approval" banner.
   */
  async function registerCompany(form) {
    const { data } = await api.post('/auth/register/company', form)
    setSession(data.token, data.user)
    return data
  }

  /**
   * fetchMe() -> GET /api/auth/me
   * what : re-pull the current user from the backend and refresh our copy.
   * why  : the cached `user` in localStorage goes stale (e.g. admin approved
   *        the company, or student updated their profile). this re-syncs it.
   */
  async function fetchMe() {
    const { data } = await api.get('/auth/me')
    state.user = data.user
    localStorage.setItem('user', JSON.stringify(data.user))
    return data.user
  }

  /**
   * dashboardPath(role) -> '/admin/dashboard' | '/company/dashboard' | '/student/dashboard'
   * what : plain role -> route lookup. no API call.
   * where: router/index.js guard (bounce a logged-in user off /login), and
   *        anywhere we need "send them home".
   * note : mirrors backend/routes.py::_dashboard_path(). keep both in sync.
   */
  function dashboardPath(role) {
    const paths = {
      admin: '/admin/dashboard',
      company: '/company/dashboard',
      student: '/student/dashboard',
    }
    return paths[role] || '/login'
  }

  // we return `token`/`user`/`isAuthenticated` as GETTERS, not plain values.
  // reason: if we did `token: state.token` it'd snapshot the value at call time
  // and never update. getters re-read `state` on every access -> stays reactive.
  return {
    get token() {
      return state.token
    },
    get user() {
      return state.user
    },
    get isAuthenticated() {
      return !!state.token
    },
    login,
    registerStudent,
    registerCompany,
    fetchMe,
    logout,
    dashboardPath,
  }
}
