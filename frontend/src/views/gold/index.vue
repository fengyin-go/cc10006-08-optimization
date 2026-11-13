<template>
  <section class="page" data-module="gold">
    <header class="page-head">
      <div>
        <h2>聚合效果视图</h2>
        <p class="page-desc">
          按聚合视图汇总上游清洗表的完成度、更新频率与数据新鲜度，给出可执行状态；
          上游状态变化实时驱动可查询范围，列表与导出回执同源。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="reload(true)">刷新口径</button>
        <button class="btn primary" type="button" @click="exportRows">导出效果视图回执</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value" :class="item.tone">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="applyFilters">
      <label class="filter-item">
        <span>视图编号</span>
        <input v-model="filters.keyword" placeholder="按视图编号检索" />
      </label>
      <label class="filter-item">
        <span>所属分层</span>
        <select v-model="filters.layer">
          <option value="">全部分层</option>
          <option v-for="layer in options.layers" :key="layer" :value="layer">{{ layer }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>更新频率</span>
        <select v-model="filters.frequency">
          <option value="">全部频率</option>
          <option v-for="freq in options.frequencies" :key="freq" :value="freq">{{ freq }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>可执行状态</span>
        <select v-model="filters.state">
          <option value="">全部状态</option>
          <option v-for="state in options.states" :key="state" :value="state">{{ state }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>视图状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="status in options.statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
      <span class="poll-hint">每 20 秒自动刷新 · 上次更新 {{ lastUpdated }}</span>
    </form>

    <table class="data-table effect-table">
      <thead>
        <tr>
          <th class="col-toggle"></th>
          <th>视图编号</th>
          <th>所属分层</th>
          <th>更新频率</th>
          <th>上游最低/平均完成度</th>
          <th>视图级状态</th>
          <th>可执行状态</th>
          <th>不可执行原因</th>
          <th>视图动作</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="view in rows" :key="String(view.id)">
          <tr :class="{ 'row-blocked': view.可执行状态 === '不可执行' }">
            <td class="col-toggle">
              <button class="link" type="button" @click="toggle(view.id)">
                {{ expanded.has(view.id) ? '收起' : '展开上游' }}
              </button>
            </td>
            <td>{{ view.视图编号 }}</td>
            <td>
              <span class="layer-badge">{{ view.所属分层 || '—' }}</span>
            </td>
            <td>{{ view.更新频率 || '—' }}</td>
            <td>
              <div class="completion-cell">
                <div class="bar"><div class="bar-fill" :style="{ width: completionWidth(view.最低完成度) }"></div></div>
                <span>{{ view.最低完成度 ?? '—' }}% / {{ view.平均完成度 ?? '—' }}%</span>
              </div>
            </td>
            <td><span class="badge" :class="badgeClass(view.视图状态)">{{ view.视图状态 }}</span></td>
            <td><span class="badge" :class="stateClass(view.可执行状态)">{{ view.可执行状态 }}</span></td>
            <td class="reason-cell">{{ view.不可执行原因 || '—' }}</td>
            <td class="row-actions">
              <button
                v-for="action in lifecycleActions"
                :key="action"
                class="link"
                type="button"
                @click="runLifecycle(action, view)"
              >
                {{ action }}
              </button>
            </td>
          </tr>
          <tr v-if="expanded.has(view.id)" class="upstream-row">
            <td></td>
            <td :colspan="8">
              <table class="data-table upstream-table">
                <thead>
                  <tr>
                    <th>上游清洗表</th>
                    <th>所属分层</th>
                    <th>完成度</th>
                    <th>更新频率</th>
                    <th>数据新鲜度</th>
                    <th>批次延迟</th>
                    <th>上游状态</th>
                    <th>质量指标</th>
                    <th>元数据版本</th>
                    <th>批次模拟</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="up in view.upstreams" :key="up.清洗表编号 || 'missing'">
                    <td>
                      <RouterLink class="link" :to="`/silver?keyword=${encodeURIComponent(up.清洗表编号)}`">
                        {{ up.清洗表编号 }}
                      </RouterLink>
                      <div class="sub-text">{{ up.清洗表名称 }}</div>
                    </td>
                    <td>{{ up.所属分层 || '—' }}</td>
                    <td>
                      <div class="completion-cell">
                        <div class="bar"><div class="bar-fill" :style="{ width: completionWidth(up.完成度) }"></div></div>
                        <span>{{ up.完成度 ?? '—' }}%</span>
                      </div>
                    </td>
                    <td>{{ up.更新频率 || '—' }}</td>
                    <td>{{ up.数据新鲜度 }}</td>
                    <td>{{ up.批次延迟 }}</td>
                    <td><span class="badge" :class="badgeClass(up.上游状态)">{{ up.上游状态 }}</span></td>
                    <td>
                      <button
                        v-if="up.质量指标.length"
                        class="link"
                        type="button"
                        @click="openQuality(up.清洗表编号)"
                      >
                        {{ up.质量指标.map((q) => q.指标编号).join('、') }}
                      </button>
                      <span v-else class="sub-text">无</span>
                    </td>
                    <td>
                      <button
                        v-if="up.元数据版本.length"
                        class="link"
                        type="button"
                        @click="openMeta(up.清洗表编号)"
                      >
                        {{ up.元数据版本.map((m) => m.条目编号 + '(' + m.属性值 + ')').join('、') }}
                      </button>
                      <span v-else class="sub-text">无</span>
                    </td>
                    <td class="row-actions">
                      <button
                        v-for="action in simulateActions"
                        :key="action"
                        class="link"
                        type="button"
                        :disabled="!up.silver_id"
                        @click="simulate(action, up.silver_id)"
                      >
                        {{ action }}
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </td>
          </tr>
        </template>
        <tr v-if="!rows.length">
          <td colspan="9" class="empty-state">当前筛选条件下没有可展示的聚合视图</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 个聚合视图 · 口径实时计算，无缓存</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { request } from '@/api/client'

type Upstream = {
  清洗表编号: string
  清洗表名称: string
  所属分层: string
  更新频率: string
  完成度: number | null
  计划完成时间: string
  最近完成时间: string
  新鲜度分钟: number | null
  数据新鲜度: string
  延迟分钟: number | null
  批次延迟: string
  上游状态: string
  可执行: boolean
  不可执行原因: string
  silver_id: number | null
  质量指标: { id: number; 指标编号: string; 指标类型: string }[]
  元数据版本: { id: number; 条目编号: string; 属性值: string }[]
}

type EffectView = {
  id: number
  视图编号: string
  所属分层: string
  聚合维度: string
  更新频率: string
  物化策略: string
  status: string
  最低完成度: number | null
  平均完成度: number | null
  可执行状态: string
  视图状态: string
  不可执行原因: string
  upstreams: Upstream[]
}

type FilterOptions = {
  layers: string[]
  frequencies: string[]
  states: string[]
  statuses: string[]
}

const ENDPOINT = '/api/gold'
const lifecycleActions = ['提交校验', '启用聚合', '停用聚合']
const simulateActions = ['模拟批次延迟', '模拟批次完成', '模拟时间异常']
const POLL_INTERVAL = 20_000

const route = useRoute()
const router = useRouter()

const rows = ref<EffectView[]>([])
const total = ref(0)
const errorMessage = ref('')
const lastUpdated = ref('')
const expanded = ref<Set<number>>(new Set())
const options = reactive<FilterOptions>({ layers: [], frequencies: [], states: [], statuses: [] })
const stats = ref([
  { label: '视图总数', value: 0, tone: '' },
  { label: '可执行视图', value: 0, tone: 'tone-ready' },
  { label: '不可执行视图', value: 0, tone: 'tone-blocked' },
  { label: '无法判定', value: 0, tone: 'tone-unknown' },
])
const filters = reactive<Record<string, string>>({
  keyword: '',
  layer: '',
  frequency: '',
  state: '',
  status: '',
})

// 筛选条件与地址栏 query 双向同步：保证“展示口径与当前筛选一致”，刷新页面也不丢口径。
const FILTER_KEYS = ['keyword', 'layer', 'frequency', 'state', 'status']

function syncFiltersFromRoute() {
  for (const key of FILTER_KEYS) {
    const value = route.query[key]
    filters[key] = Array.isArray(value) ? String(value[0] ?? '') : String(value ?? '')
  }
}

function querySignature(): string {
  return FILTER_KEYS.map((key) => String(route.query[key] ?? '')).join('')
}

// 记录已加载口径：地址栏被替换成相同 query 时不重复请求，避免一次筛选两次拉取。
let loadedSignature = ''

function applyFilters() {
  // 用户点“查询/重置”只负责把本地筛选写回地址栏，真正的重新加载由路由 watcher 统一驱动。
  const query: Record<string, string> = {}
  for (const key of FILTER_KEYS) {
    if (filters[key]) query[key] = filters[key]
  }
  void router.replace({ query })
}

const queryString = computed(() => {
  const params = new URLSearchParams()
  for (const key of FILTER_KEYS) {
    if (filters[key]) params.set(key, filters[key])
  }
  return params.toString()
})

function completionWidth(value: number | null): string {
  if (value === null || Number.isNaN(value)) return '0%'
  return `${Math.max(0, Math.min(100, value))}%`
}

function stateClass(state: string): string {
  if (state === '可执行') return 'badge-ready'
  if (state === '不可执行') return 'badge-blocked'
  return 'badge-unknown'
}

function badgeClass(state: string): string {
  switch (state) {
    case '健康':
      return 'badge-ready'
    case '未完成':
    case '新鲜度超标':
      return 'badge-blocked'
    case '时间异常':
    case '上游缺失':
      return 'badge-danger'
    default:
      return 'badge-unknown'
  }
}

function toggle(id: number) {
  const next = new Set(expanded.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expanded.value = next
}

function resetFilters() {
  for (const key of FILTER_KEYS) filters[key] = ''
  applyFilters()
}

function openQuality(silverCode: string) {
  void router.push({ path: '/quality', query: { monitor_object: silverCode } })
}

function openMeta(silverCode: string) {
  void router.push({ path: '/meta', query: { object_name: silverCode } })
}

function exportRows() {
  // 与列表完全相同的筛选参数，后端走同一个计算入口，保证回执同源。
  const suffix = queryString.value ? `?${queryString.value}` : ''
  window.open(`${ENDPOINT}/effects/export${suffix}`, '_blank')
}

async function runLifecycle(action: string, view: EffectView) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${view.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || '聚合视图动作未生效')
    }
    await reload(true)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '聚合视图操作失败'
  }
}

async function simulate(action: string, silverId: number | null) {
  if (!silverId) return
  errorMessage.value = ''
  try {
    const response = await request(`/api/silver/${silverId}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || '批次模拟未生效')
    }
    await reload(true)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批次模拟失败'
  }
}

async function loadOptions() {
  try {
    const response = await request(`${ENDPOINT}/effects/filters`)
    if (!response.ok) return
    const payload = (await response.json()) as FilterOptions
    options.layers = payload.layers ?? []
    options.frequencies = payload.frequencies ?? []
    options.states = payload.states ?? []
    options.statuses = payload.statuses ?? []
  } catch {
    // 筛选项拉取失败不阻断主列表，下拉保持空选项即可。
  }
}

async function loadSummary() {
  const suffix = queryString.value ? `?${queryString.value}` : ''
  try {
    const response = await request(`${ENDPOINT}/effects/summary${suffix}`)
    if (!response.ok) return
    const payload = (await response.json()) as Record<string, number>
    stats.value[0].value = payload.视图总数 ?? 0
    stats.value[1].value = payload.可执行视图 ?? 0
    stats.value[2].value = payload.不可执行视图 ?? 0
    stats.value[3].value = payload.无法判定视图 ?? 0
  } catch {
    // 统计失败时保留上一次数值，不影响列表查看。
  }
}

async function reload(force = false) {
  // 只负责按当前地址栏口径拉数据；地址栏变更由路由 watcher 统一调度，避免重复请求。
  const signature = querySignature()
  if (!force && signature === loadedSignature) return
  loadedSignature = signature
  errorMessage.value = ''
  const suffix = queryString.value ? `?${queryString.value}&size=100` : '?size=100'
  try {
    const response = await request(`${ENDPOINT}/effects${suffix}`)
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}))
      throw new Error(detail.detail || '聚合效果视图读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    lastUpdated.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    void loadSummary()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '聚合效果视图读取失败'
  }
}

let timer: number | undefined
function startPolling() {
  stopPolling()
  timer = window.setInterval(() => {
    // 页面不可见时暂停轮询，切回标签页立即强制刷新一次。
    if (document.visibilityState === 'visible') void reload(true)
  }, POLL_INTERVAL)
}
function stopPolling() {
  if (timer !== undefined) window.clearInterval(timer)
}
function onVisibility() {
  if (document.visibilityState === 'visible') void reload(true)
}

watch(
  () => route.query,
  () => {
    // 地址栏是唯一口径来源：query 一变就同步本地筛选并按新口径重新加载。
    syncFiltersFromRoute()
    void reload()
  },
)

onMounted(async () => {
  syncFiltersFromRoute()
  await loadOptions()
  await reload(true)
  startPolling()
  document.addEventListener('visibilitychange', onVisibility)
})

onBeforeUnmount(() => {
  stopPolling()
  document.removeEventListener('visibilitychange', onVisibility)
})
</script>
