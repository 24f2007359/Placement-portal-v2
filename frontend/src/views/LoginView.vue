<template>
  <div class="auth-card mt-5">
    <div class="card shadow-sm">
      <div class="card-body p-4">
        <h2 class="card-title text-center mb-4">Login</h2>

        <div v-if="error" class="alert alert-danger">{{ error }}</div>

        <form @submit.prevent="handleLogin">
          <div class="mb-3">
            <label class="form-label">Email</label>
            <input v-model="form.email" type="email" class="form-control" required />
          </div>
          <div class="mb-3">
            <label class="form-label">Password</label>
            <input v-model="form.password" type="password" class="form-control" required minlength="6" />
          </div>
          <button class="btn btn-primary w-100" type="submit" :disabled="loading">
            {{ loading ? 'Logging in...' : 'Login' }}
          </button>
        </form>

        <hr class="my-4" />
        <p class="text-center mb-2">Don't have an account?</p>
        <div class="d-grid gap-2">
          <router-link to="/register/student" class="btn btn-outline-secondary">Register as Student</router-link>
          <router-link to="/register/company" class="btn btn-outline-secondary">Register as Company</router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '../services/auth'

const router = useRouter()
const auth = useAuth()

const form = reactive({
  email: '',
  password: '',
})

const loading = ref(false)
const error = ref('')

async function handleLogin() {
  loading.value = true
  error.value = ''
  try {
    const data = await auth.login(form.email, form.password)
    router.push(data.redirect)
  } catch (err) {
    error.value = err.response?.data?.error || 'Login failed'
  } finally {
    loading.value = false
  }
}
</script>
