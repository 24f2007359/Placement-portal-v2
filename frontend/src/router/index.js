// =============================================================================
// FILE : src/router/index.js
// WHAT : the route table + the global auth/role guard.
// WHY  : this is the frontend's RBAC layer. it stops a student from even
//        NAVIGATING to /admin/dashboard.
//
// !! IMPORTANT !! this guard is UX, not security. it's all client-side JS --
//    anyone can bypass it with devtools. the REAL enforcement is the
//    @role_required("admin") decorator in backend/auth_utils.py. even if you
//    force your way onto /admin/dashboard, every API call it fires comes back
//    403 and you see an empty shell. never trust the frontend.
//
// USED BY: src/main.js -> createApp(App).use(router)
// READS  : services/auth.js -> isAuthenticated, user.role, dashboardPath()
// =============================================================================

import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '../services/auth'
import LoginView from '../views/LoginView.vue'
import RegisterStudentView from '../views/RegisterStudentView.vue'
import RegisterCompanyView from '../views/RegisterCompanyView.vue'
import AdminDashboard from '../views/AdminDashboard.vue'
import CompanyDashboard from '../views/CompanyDashboard.vue'
import StudentDashboard from '../views/StudentDashboard.vue'

const router = createRouter({
  // createWebHistory = clean URLs (/login) instead of hash URLs (/#/login).
  // needs the dev server / prod server to fall back to index.html on refresh,
  // which vite does out of the box.
  history: createWebHistory(),

  // `meta` is just a bag of custom flags WE invented. vue-router doesn't care
  // what's in it -- our beforeEach() below is the thing that reads them.
  //   meta.guest       -> "logged-in users should NOT see this page"
  //   meta.requiresAuth-> "must be logged in"
  //   meta.role        -> "must be exactly this role"
  routes: [
    { path: '/', redirect: '/login' },
    { path: '/login', name: 'login', component: LoginView, meta: { guest: true } },
    { path: '/register/student', name: 'register-student', component: RegisterStudentView, meta: { guest: true } },
    { path: '/register/company', name: 'register-company', component: RegisterCompanyView, meta: { guest: true } },
    { path: '/admin/dashboard', name: 'admin-dashboard', component: AdminDashboard, meta: { requiresAuth: true, role: 'admin' } },
    { path: '/company/dashboard', name: 'company-dashboard', component: CompanyDashboard, meta: { requiresAuth: true, role: 'company' } },
    { path: '/student/dashboard', name: 'student-dashboard', component: StudentDashboard, meta: { requiresAuth: true, role: 'student' } },
  ],
})

// -----------------------------------------------------------------------------
// GLOBAL NAVIGATION GUARD
// runs before EVERY route change, including the very first page load.
//
// return value contract:
//   return true          -> allow the navigation
//   return '/some/path'  -> cancel it and redirect there instead
//
// three rules, checked in order:
// -----------------------------------------------------------------------------
router.beforeEach((to) => {
  const auth = useAuth()

  // RULE 1: page needs a login and you don't have one -> go log in.
  // e.g. paste /admin/dashboard into the URL bar while logged out.
  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    return '/login'
  }

  // RULE 2: page is for logged-OUT people only (login / register), but you're
  // already in -> shove you at your own dashboard.
  // stops the weird state of being logged in and staring at a login form.
  if (to.meta.guest && auth.isAuthenticated) {
    return auth.dashboardPath(auth.user.role)
  }

  // RULE 3: right, you're logged in -- but is it YOUR dashboard?
  // a student poking at /company/dashboard gets kicked to /student/dashboard.
  // the `auth.isAuthenticated ? ... : '/login'` ternary is a paranoia guard for
  // the edge case where token exists but user object somehow doesn't.
  if (to.meta.role && auth.user?.role !== to.meta.role) {
    return auth.isAuthenticated ? auth.dashboardPath(auth.user.role) : '/login'
  }

  return true // nothing tripped -> let 'em through
})

export default router
