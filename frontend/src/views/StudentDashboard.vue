<template>
  <div class="dashboard-card">
    <div class="card shadow-sm">
      <div class="card-body p-4">
        <h2 class="card-title">Student Dashboard</h2>
        <p class="text-muted">Welcome, {{ auth.user?.profile?.full_name }}</p>

        <div v-if="error" class="alert alert-danger">{{ error }}</div>
        <div v-else-if="loading" class="alert alert-info">Loading dashboard...</div>
        <div v-else-if="dashboard" class="alert alert-success">{{ dashboard.message }}</div>

        <ul class="list-group mt-3">
          <li class="list-group-item">Browse approved placement drives</li>
          <li class="list-group-item">Apply for jobs and track status</li>
          <li class="list-group-item">View interview schedules and feedback</li>
        </ul>
        <p class="text-muted mt-3 mb-0">Full student features will be added in Milestone 5.</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import api from '../services/api'
import { useAuth } from '../services/auth'

const auth = useAuth()
const dashboard = ref(null)
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    const { data } = await api.get('/student/dashboard')
    dashboard.value = data
  } catch (err) {
    error.value = err.response?.data?.error || 'Failed to load dashboard'
  } finally {
    loading.value = false
  }
})
</script>
