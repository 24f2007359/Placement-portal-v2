<!--
  =============================================================================
  FILE : src/App.vue
  WHAT : the root component. it is basically just a navbar + a hole for the
         current page to render into.
  WHY  : the navbar (who am i / logout) needs to show on EVERY logged-in page,
         so it lives here instead of being copy-pasted into all 6 views.
  MOUNTED BY: src/main.js -> createApp(App)
  RENDERS   : <router-view/> -> whatever route/index.js matched
               /login              -> LoginView.vue
               /register/student   -> RegisterStudentView.vue
               /register/company   -> RegisterCompanyView.vue
               /admin/dashboard    -> AdminDashboard.vue
               /company/dashboard  -> CompanyDashboard.vue
               /student/dashboard  -> StudentDashboard.vue
  =============================================================================
-->
<template>
  <div>
    <!--
      navbar only exists when logged in.
      v-if (not v-show) -> we want it fully GONE on the login/register screens,
      not just hidden with display:none.
      auth.isAuthenticated is a getter on services/auth.js -> !!state.token,
      so this flips the instant login()/logout() runs. no manual refresh needed.
    -->
    <nav v-if="auth.isAuthenticated" class="navbar navbar-expand-lg navbar-dark bg-primary mb-4">
      <div class="container">
        <router-link class="navbar-brand" to="/">Placement Portal</router-link>
        <div class="navbar-nav ms-auto">
          <!--
            ?. (optional chaining) everywhere because on the very first paint
            `user` can still be null while localStorage is being read.
            without ?. you get "cannot read property email of null" and a white screen.
          -->
          <span class="navbar-text text-white me-3">{{ auth.user?.email }} ({{ auth.user?.role }})</span>
          <button class="btn btn-outline-light btn-sm" @click="logout">Logout</button>
        </div>
      </div>
    </nav>

    <!-- the actual page gets injected here by vue-router -->
    <main class="container pb-5">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { useAuth } from './services/auth'

const router = useRouter()
const auth = useAuth() // shared reactive auth state, see services/auth.js

/**
 * logout()
 * what : wipe token + user from memory AND localStorage, then bounce to /login.
 * where: the Logout button in the navbar above.
 * note : we push('/login') manually instead of letting the router guard do it.
 *        the guard would only fire on the NEXT navigation, so without this you'd
 *        sit on the dashboard staring at a half-dead page.
 * note2: nothing is called on the backend. JWT is stateless -- we just throw our
 *        copy of the token away. it stays technically valid until it expires.
 */
function logout() {
  auth.logout()
  router.push('/login')
}
</script>
