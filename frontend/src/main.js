// =============================================================================
// FILE : src/main.js
// WHAT : the entry point. vite loads index.html -> index.html loads this ->
//        this boots vue and glues everything together.
// WHY  : one place to register app-wide plugins (router) + pull in global CSS.
// =============================================================================

import { createApp } from 'vue'
import App from './App.vue' // the root component (navbar + <router-view/>)
import router from './router' // route table + the auth guard

// bootstrap CSS first, THEN our overrides. order matters --
// assets/main.css defines .modal-backdrop-custom / .timeline (M6 modals) and
// would get steamrolled if bootstrap loaded after it.
import 'bootstrap/dist/css/bootstrap.min.css'
import 'bootstrap/dist/js/bootstrap.bundle.min.js' // needed for dropdowns/collapse
import './assets/main.css'

// createApp(App)      -> build the vue instance around the root component
// .use(router)        -> installs vue-router, enables <router-link>/<router-view>
//                        and the beforeEach guard in router/index.js
// .mount('#app')      -> jam it into <div id="app"> in index.html
createApp(App).use(router).mount('#app')
