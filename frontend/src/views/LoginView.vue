<!--
  =============================================================================
  FILE : src/views/LoginView.vue
  ROUTE: /login   (meta.guest = true -> logged-in users get bounced away)
  WHAT : the one login form for ALL THREE roles. admin, company, student --
         same box. backend figures out who you are from the email.
  WHY one form? -> the User table is unified (one table, a `role` enum column),
         see backend/models.py::User. so one /api/auth/login handles everyone.

  FLOW : type creds -> auth.login() -> backend verifies pw hash -> returns
         { token, user, redirect } -> we push(redirect) and land on the right
         dashboard. the backend TELLS us where to go (data.redirect), we don't
         guess client-side.
  =============================================================================
-->
<template>
  <div class="auth-card mt-5">
    <div class="card shadow-sm">
      <div class="card-body p-4">
        <h2 class="card-title text-center mb-4">Login</h2>

        <!-- red bar. only rendered when error is a non-empty string (v-if on '') -->
        <div v-if="error" class="alert alert-danger">{{ error }}</div>

        <!--
          @submit.prevent -> .prevent kills the browser's default form POST +
          full page reload. without it vue never sees the event and the SPA dies.
        -->
        <form @submit.prevent="handleLogin">
          <div class="mb-3">
            <label class="form-label">Email</label>
            <!-- v-model = two-way bind. typing here mutates form.email live -->
            <input v-model="form.email" type="email" class="form-control" required />
          </div>
          <div class="mb-3">
            <label class="form-label">Password</label>
            <!--
              minlength=6 mirrors the backend rule in routes.py::_validate_credentials.
              browser-side validation is just a nicety -- backend re-checks it.
            -->
            <input v-model="form.password" type="password" class="form-control" required minlength="6" />
          </div>
          <!-- :disabled while in-flight so an impatient user can't double-submit -->
          <button class="btn btn-primary w-100" type="submit" :disabled="loading">
            {{ loading ? 'Logging in...' : 'Login' }}
          </button>
        </form>

        <hr class="my-4" />
        <p class="text-center mb-2">Don't have an account?</p>
        <div class="d-grid gap-2">
          <!-- note: no "Register as Admin" link. admin is pre-seeded by
               backend/seed_admin.py and has NO registration route, on purpose. -->
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

// reactive() for the form object (many fields, mutate .email/.password directly)
// ref() for lone primitives (need .value to read/write in JS, auto-unwrapped in template)
const form = reactive({
  email: '',
  password: '',
})

const loading = ref(false)
const error = ref('')

/**
 * handleLogin()
 * what : submit handler for the form above.
 * calls: services/auth.js -> login() -> POST /api/auth/login
 * on ok : auth.js has already stashed the JWT in localStorage, so we just
 *         router.push(data.redirect). redirect is '/admin/dashboard' etc,
 *         computed backend-side by routes.py::_dashboard_path().
 * on err: axios throws on any 4xx. dig the real message out of
 *         err.response.data.error -> e.g.
 *           401 "Invalid email or password"
 *           403 "Account is deactivated" / "Student account is blacklisted"
 *         the ?. chain is because a NETWORK failure has no .response at all,
 *         and then we fall back to the generic 'Login failed'.
 * finally: always drop `loading`, even on error, else the button stays stuck.
 */
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
