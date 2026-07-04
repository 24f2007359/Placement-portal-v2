<template>
  <div>
    <nav v-if="auth.isAuthenticated" class="navbar navbar-expand-lg navbar-dark bg-primary mb-4">
      <div class="container">
        <router-link class="navbar-brand" to="/">Placement Portal</router-link>
        <div class="navbar-nav ms-auto">
          <span class="navbar-text text-white me-3">{{ auth.user?.email }} ({{ auth.user?.role }})</span>
          <button class="btn btn-outline-light btn-sm" @click="logout">Logout</button>
        </div>
      </div>
    </nav>
    <main class="container pb-5">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { useAuth } from './services/auth'

const router = useRouter()
const auth = useAuth()

function logout() {
  auth.logout()
  router.push('/login')
}
</script>
