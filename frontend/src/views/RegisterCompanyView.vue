<!--
  =============================================================================
  FILE : src/views/RegisterCompanyView.vue
  ROUTE: /register/company   (meta.guest = true)
  WHAT : company signup form.

  !! THE GOTCHA !! registering does NOT get you a working account.
  backend creates the Company row with approval_status = PENDING. you DO get a
  JWT and you DO land on /company/dashboard -- but the very first API call that
  dashboard makes (GET /api/company/dashboard) comes back 403, because
  company_routes.py::_ensure_company_access() refuses anyone not APPROVED.

  CompanyDashboard.vue catches that 403 in onMounted() and flips on the yellow
  "your profile is pending, dashboard access needs admin approval" banner.

  so the real unlock is: an ADMIN clicks Approve in AdminDashboard.vue ->
  PUT /api/admin/companies/:id/approve. only then does the dashboard populate,
  and only then can their job postings be approved either.

  BACKEND: POST /api/auth/register/company -> routes.py::register_company()
           makes User(role=COMPANY) + Company(approval_status=PENDING), 1:1.
  =============================================================================
-->
<template>
  <div class="auth-card mt-5">
    <div class="card shadow-sm">
      <div class="card-body p-4">
        <h2 class="card-title text-center mb-4">Company Registration</h2>

        <div v-if="error" class="alert alert-danger">{{ error }}</div>

        <form @submit.prevent="handleRegister">
          <!-- ===== REQUIRED ===== -->
          <div class="mb-3">
            <label class="form-label">Company Name</label>
            <!-- NOT unique in the db (two "Acme"s can exist). only email is unique. -->
            <input v-model="form.name" type="text" class="form-control" required />
          </div>
          <div class="mb-3">
            <label class="form-label">Email</label>
            <!-- this is the LOGIN email. 409 if already taken. -->
            <input v-model="form.email" type="email" class="form-control" required />
          </div>
          <div class="mb-3">
            <label class="form-label">Password</label>
            <input v-model="form.password" type="password" class="form-control" required minlength="6" />
          </div>

          <!-- ===== OPTIONAL PROFILE STUFF ===== -->
          <div class="mb-3">
            <label class="form-label">Industry</label>
            <!-- admin can search/filter companies by industry (GET /api/admin/companies?industry=) -->
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
            <!--
              WORTH FILLING IN: the M7 monthly placement report job
              (tasks.py::_build_company_report) mails the PDF to hr_contact IF it
              looks like an email, else it falls back to the login email above.
            -->
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

// keys must match routes.py::register_company()'s data.get(...) calls.
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

/**
 * handleRegister()
 * calls: services/auth.js -> registerCompany(form) -> POST /api/auth/register/company
 * on ok : backend replies 201 with a token + redirect '/company/dashboard'.
 *         its `message` even says "Awaiting admin approval." we push anyway --
 *         the dashboard itself shows the pending banner (see file header).
 * on err: 409 "Email already registered", 400 "Company name is required", etc.
 */
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
