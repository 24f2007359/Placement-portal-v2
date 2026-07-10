<!--
  =============================================================================
  FILE : src/views/RegisterStudentView.vue
  ROUTE: /register/student   (meta.guest = true)
  WHAT : student self-signup form.
  WHY  : students register themselves, no gatekeeping. contrast with
         RegisterCompanyView.vue where an admin must approve before the account
         is usable.

  BACKEND: POST /api/auth/register/student -> routes.py::register_student()
           creates BOTH a User(role=STUDENT) row and a Student profile row,
           linked 1:1, in one transaction.

  KEY DIFFERENCE vs company: you're logged in and usable IMMEDIATELY. the
  backend hands back a JWT right there in the register response, so we skip the
  login screen entirely and go straight to /student/dashboard.
  =============================================================================
-->
<template>
  <div class="auth-card mt-5">
    <div class="card shadow-sm">
      <div class="card-body p-4">
        <h2 class="card-title text-center mb-4">Student Registration</h2>

        <div v-if="error" class="alert alert-danger">{{ error }}</div>

        <form @submit.prevent="handleRegister">
          <!-- ===== REQUIRED FIELDS (backend 400s without these) ===== -->
          <div class="mb-3">
            <label class="form-label">Full Name</label>
            <input v-model="form.full_name" type="text" class="form-control" required />
          </div>
          <div class="mb-3">
            <label class="form-label">Email</label>
            <!-- backend 409s "Email already registered" if it's taken (unique col) -->
            <input v-model="form.email" type="email" class="form-control" required />
          </div>
          <div class="mb-3">
            <label class="form-label">Password</label>
            <!-- hashed with werkzeug generate_password_hash. never stored plain. -->
            <input v-model="form.password" type="password" class="form-control" required minlength="6" />
          </div>

          <!-- ===== OPTIONAL FIELDS ===== -->
          <div class="mb-3">
            <label class="form-label">Institute ID</label>
            <!-- optional BUT unique if given -> backend 409s on a dupe roll number -->
            <input v-model="form.institute_id" type="text" class="form-control" />
          </div>
          <div class="mb-3">
            <label class="form-label">Contact</label>
            <input v-model="form.contact" type="text" class="form-control" />
          </div>
          <div class="mb-3">
            <label class="form-label">Branch</label>
            <!--
              branch matters LATER: _check_eligibility() in student_routes.py
              compares it against job.eligibility_branch when you hit Apply.
              blank branch = can't apply to branch-restricted drives.
              cgpa + grad year get filled in on the dashboard Profile tab.
            -->
            <input v-model="form.branch" type="text" class="form-control" />
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

// keys here MUST match what routes.py::register_student() reads out of the
// json body. rename one and it silently becomes None on the backend.
const form = reactive({
  full_name: '',
  email: '',
  password: '',
  institute_id: '',
  contact: '',
  branch: '',
})

const loading = ref(false)
const error = ref('')

/**
 * handleRegister()
 * calls: services/auth.js -> registerStudent(form) -> POST /api/auth/register/student
 * on ok : auth.js already stashed the token (setSession). push straight to
 *         data.redirect ('/student/dashboard'). no login step needed.
 * on err: common ones ->
 *         409 "Email already registered"
 *         409 "Institute ID already registered"
 *         400 "Password must be at least 6 characters"
 * note : we pass the whole `form` object. reactive() proxies serialize fine
 *        through axios/JSON.stringify, no need to spread it.
 */
async function handleRegister() {
  loading.value = true
  error.value = ''
  try {
    const data = await auth.registerStudent(form)
    router.push(data.redirect)
  } catch (err) {
    error.value = err.response?.data?.error || 'Registration failed'
  } finally {
    loading.value = false
  }
}
</script>
