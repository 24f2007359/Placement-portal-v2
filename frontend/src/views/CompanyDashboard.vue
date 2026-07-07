<template>
  <div class="dashboard-card">
    <div class="card shadow-sm">
      <div class="card-body p-4">
        <h2 class="card-title">Company Dashboard</h2>
        <p class="text-muted">{{ auth.user?.profile?.name }}</p>

        <div v-if="error" class="alert alert-danger">{{ error }}</div>
        <div v-else-if="loading" class="alert alert-info">Loading dashboard...</div>
        <div v-else-if="pendingApproval" class="alert alert-warning">
          Your company profile is <strong>{{ approvalStatus }}</strong>.
          You can log in, but dashboard access is available only after admin approval.
        </div>
        <div v-else-if="dashboard" class="alert alert-success">{{ dashboard.message }}</div>

        <ul v-if="dashboard && !pendingApproval" class="list-group mt-3">
          <li class="list-group-item">Post job positions and placement drives</li>
          <li class="list-group-item">Review student applications</li>
          <li class="list-group-item">Shortlist candidates and schedule interviews</li>
        </ul>
        <p v-if="dashboard && !pendingApproval" class="text-muted mt-3 mb-0">Full company features will be added in Milestone 4.</p>
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
const pendingApproval = ref(false)
const approvalStatus = ref('')

onMounted(async () => {
  try {
    const { data } = await api.get('/company/dashboard')
    dashboard.value = data
  } catch (err) {
    if (err.response?.status === 403) {
      pendingApproval.value = true
      approvalStatus.value = err.response.data.approval_status || 'pending'
    } else {
      error.value = err.response?.data?.error || 'Failed to load dashboard'
    }
  } finally {
    loading.value = false
  }
})
</script>
