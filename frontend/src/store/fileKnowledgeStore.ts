import { create } from 'zustand'
import type { KnowledgeFileUploadResult } from '../services/api'

export type SelectedSku = {
  sku: string
  label: string
}

type FileKnowledgeState = {
  files: File[]
  skuQuery: string
  selectedSkus: SelectedSku[]
  results: KnowledgeFileUploadResult[]
  setFiles: (files: File[]) => void
  addFiles: (files: File[]) => void
  removeFile: (index: number) => void
  clearFiles: () => void
  setSkuQuery: (value: string) => void
  addSku: (item: SelectedSku) => void
  removeSku: (sku: string) => void
  clearSkus: () => void
  setResults: (results: KnowledgeFileUploadResult[]) => void
  resetDraft: () => void
}

export const useFileKnowledgeStore = create<FileKnowledgeState>((set) => ({
  files: [],
  skuQuery: '',
  selectedSkus: [],
  results: [],
  setFiles: (files) => set({ files }),
  addFiles: (files) =>
    set((state) => {
      const existing = new Set(
        state.files.map((file) => `${file.name}:${file.size}:${file.lastModified}`),
      )
      const next = [...state.files]
      for (const file of files) {
        const key = `${file.name}:${file.size}:${file.lastModified}`
        if (!existing.has(key)) {
          existing.add(key)
          next.push(file)
        }
      }
      return { files: next }
    }),
  removeFile: (index) =>
    set((state) => ({ files: state.files.filter((_, fileIndex) => fileIndex !== index) })),
  clearFiles: () => set({ files: [] }),
  setSkuQuery: (value) => set({ skuQuery: value }),
  addSku: (item) => {
    const sku = String(item.sku || '').trim().toUpperCase()
    if (!sku) return
    set((state) => {
      if (state.selectedSkus.some((existing) => existing.sku === sku)) return {}
      return {
        skuQuery: '',
        selectedSkus: [...state.selectedSkus, { sku, label: item.label || sku }],
      }
    })
  },
  removeSku: (sku) =>
    set((state) => ({ selectedSkus: state.selectedSkus.filter((item) => item.sku !== sku) })),
  clearSkus: () => set({ selectedSkus: [] }),
  setResults: (results) => set({ results }),
  resetDraft: () =>
    set({
      files: [],
      skuQuery: '',
      selectedSkus: [],
      results: [],
    }),
}))

export function getSelectedSkuSet(selectedSkus: SelectedSku[]) {
  return new Set(selectedSkus.map((item) => item.sku))
}

export function normalizeSkuText(value: string) {
  return value.trim().toUpperCase()
}

export function parseManualSkuInput(text: string) {
  return Array.from(
    new Set(
      text
        .split(/[,，;\n]+/)
        .map((item) => item.trim().toUpperCase())
        .filter(Boolean),
    ),
  )
}
