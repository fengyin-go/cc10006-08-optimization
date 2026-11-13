<template>
  <section class="page" data-module="silver">
    <header class="page-head">
      <div>
        <h2>清洗层管理</h2>
        <p class="page-desc">
          维护清洗表的批次完成度与时间字段；批次模拟的变化会立即驱动聚合效果视图的可执行结论。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记清洗表</button>
        <button class="btn" type="button" @click="exportRows">导出清洗层管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>表编号</span>
        <input v-model="filters.keyword" placeholder="按表编号检索" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="state in statuses" :key="state" :value="state">{{ state }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>生命周期动作</th>
          <th>批次模拟（联动聚合效果视图）</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <template v-if="column === '完成度'">
              <div class="completion-cell">
                <div class="bar"><div class="bar-fill" :style="{ width: `${row.完成度 ?? 0}%` }"></div></div>
                <span>{{ row.完成度 ?? '—' }}%</span>
              </div>
            </template>
            <template v-else-if="column === '批次状态'">
              <span class="badge" :class="batchClass(String(row.批次状态))">{{ row.批次状态 ?? '—' }}</span>
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
          <td class="row-actions">
            <button
              v-for="action in simulateActions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无清洗层管理数据，可先登记清洗表</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条清洗层管理记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const route = useRoute()
const ENDPOINT = '/api/silver'
const columns = [
  '表编号', '上游原始表', '所属分层', '更新频率', '完成度', '批次状态',
  '计划完成时间', '最近完成时间', '输出路径', '调度周期',
]
const actions = ['提交校验', '启用清洗', '停用清洗']
const simulateActions = ['模拟批次延迟', '模拟批次完成', '模拟时间异常']
const statuses = ['草稿', '待校验', '已启用', '已停用']
const stats = [{ label: '清洗表总数', value: 0 }, { label: '已启用表', value: 0 }, { label: '异常批次', value: 0 }]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})

function batchClass(state: string): string {
  if (state === '正常') return 'badge-ready'
  if (state === '延迟') return 'badge-blocked'
  if (state === '时间异常') return 'badge-danger'
  return 'badge-unknown'
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  window.open(`${ENDPOINT}/export?${query}`, '_blank')
}

function openCreate() {
  errorMessage.value = '清洗表登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json().catch(() => ({}))
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || '清洗层管理动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '清洗层管理操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const params: Record<string, string> = { ...filters.value }
  // 支持从聚合效果视图带表编号跳转定位。
  if (route.query.keyword && !params.keyword) {
    params.keyword = String(route.query.keyword)
  }
  const query = new URLSearchParams(params).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('清洗表列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    stats[0].value = total.value
    stats[1].value = rows.value.filter((row) => row.status === '已启用').length
    stats[2].value = rows.value.filter((row) => row.abnormal).length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '清洗层管理列表读取失败'
  }
}

onMounted(reload)
</script>
