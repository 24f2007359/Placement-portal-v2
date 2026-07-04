<template>
  <div class="auth-card mt-5">
    <div class="card shadow-sm">
      <div class="card-body p-4">
        <h2 class="card-title text-center mb-4">Company Registration</h2>

        <div v-if="error" class="alert alert-danger">{{ error }}</div>

        <form @submit.prevent="handleRegister">
          <div class="mb-3">
            <label class="form-label">Company Name</label>
            <input v-model="form.name" type="text" class="form-control" required />
          </div>
          <div class="mb-3">
            <label class="form-label">Email</label>
            <input v-model="form.email" type="email" class="form-control" required />
          </div>
          <div class="mb-3">
            <label class="form-label">Password</label>
            <input v-model="form.password" type="password" class="form-control" required minlength="6" />
          </div>
          <div class="mb-3">
            <label class="form-label">Industry</label>
            <input v-model="form.industry" type="text" class="form-control" />
          </div>
          <div class="mb-3">
            <label class="form-label">Location</label>
            <input v-model="form.location" type="text" class="form-control" />
          </div>
          <div class="mb-3">
            <label class="form-label">Website</label>
            <input v-model="form.website" type="url" class="form-control" />
          </div>
          <div class="mb-3">
            <label class="form-label">HR Contact</label>
            <input v-model="form.hr_contact" type="text" class="form-control" />
          </div>
          <div class="mb-3">
            <label class="form-label">Description</label>
            <textarea v-model="form.description" class="form-control" rows="3"></textarea>
          </div>
          <button class="btn btn-primary w-100" type="submit" :disabled="loading">
            {{ loading ? 'Registering...' : 'Register' }}
          </button>
        </form>

        <p class="text-center mt-3 mb-0">
          Already have an account? <router-link to="/login">Login</router-link>
        </p>
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
  name: '',
  email: '',
  password: '',
  industry: '',
  location: '',
  website: '',
  hr_contact: '',
  description: '',
})

const loading = ref(false)
const error = ref('')

async function handleRegister() {
  loading.value = true
  error.value = ''
  try {
    const data = await auth.registerCompany(form)
    router.push(data.redirect)
  } catch (err) {
    error.value = err.response?.data?.error || 'Registration failed'
  } finally {
    loading.value = false
  }
}
</script>
