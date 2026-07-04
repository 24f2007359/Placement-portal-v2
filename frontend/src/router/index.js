import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '../services/auth'
import LoginView from '../views/LoginView.vue'
import RegisterStudentView from '../views/RegisterStudentView.vue'
import RegisterCompanyView from '../views/RegisterCompanyView.vue'
import AdminDashboard from '../views/AdminDashboard.vue'
import CompanyDashboard from '../views/CompanyDashboard.vue'
import StudentDashboard from '../views/StudentDashboard.vue'

const router = createRouter({
  history: createWebHistory(),
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

router.beforeEach((to) => {
  const auth = useAuth()

  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    return '/login'
  }

  if (to.meta.guest && auth.isAuthenticated) {
    return auth.dashboardPath(auth.user.role)
  }

  if (to.meta.role && auth.user?.role !== to.meta.role) {
    return auth.isAuthenticated ? auth.dashboardPath(auth.user.role) : '/login'
  }

  return true
})

export default router
