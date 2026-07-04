import { reactive } from 'vue'
import api from './api'

const state = reactive({
  token: localStorage.getItem('token'),
  user: JSON.parse(localStorage.getItem('user') || 'null'),
})

export function useAuth() {
  function setSession(token, user) {
    state.token = token
    state.user = user
    localStorage.setItem('token', token)
    localStorage.setItem('user', JSON.stringify(user))
  }

  function logout() {
    state.token = null
    state.user = null
    localStorage.removeItem('token')
    localStorage.removeItem('user')
  }

  async function login(email, password) {
    const { data } = await api.post('/auth/login', { email, password })
    setSession(data.token, data.user)
    return data
  }

  async function registerStudent(form) {
    const { data } = await api.post('/auth/register/student', form)
    setSession(data.token, data.user)
    return data
  }

  async function registerCompany(form) {
    const { data } = await api.post('/auth/register/company', form)
    setSession(data.token, data.user)
    return data
  }

  async function fetchMe() {
    const { data } = await api.get('/auth/me')
    state.user = data.user
    localStorage.setItem('user', JSON.stringify(data.user))
    return data.user
  }

  function dashboardPath(role) {
    const paths = {
      admin: '/admin/dashboard',
      company: '/company/dashboard',
      student: '/student/dashboard',
    }
    return paths[role] || '/login'
  }

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
