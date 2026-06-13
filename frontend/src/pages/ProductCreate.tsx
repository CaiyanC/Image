import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, type CategoryItem } from '../services/api'
import type { ProductDraft } from '../types'

interface DimensionLine {
  label: string
  value: string
  unit: string
}

interface CapacityLine {
  label: string
  value: string
}

interface Specs {
  size_info?: DimensionLine[]
  capacity?: CapacityLine[]
  gross_weight_g?: number
  body_material?: string
  color?: string
  surface_finish?: string
  heat_source?: string
  power?: string
  technical_advantages?: string[]
  usage_instruction?: string
}

interface BusinessInfo {
  top_selling_points?: string[]
  target_audience?: string
  positioning?: string
  price_positioning?: string
  emotional_value?: string
  usage_scenarios?: string[]
  competitor_benchmark?: { name: string; url?: string }[]
}

interface ContentAssets {
  title_en?: string
  title_cn?: string
  long_description_en?: string
  long_description_cn?: string
  long_description_ja?: string
  bullet_points?: string[]
  listing_cn?: string
  listing_en?: string
  listing_ja?: string
  a_plus_content?: string
  search_keywords?: { keyword: string; priority: string }[]
}

interface MediaAssets {
  source_white_bg?: string[]
  source_multi_angle?: string[]
  source_structure?: string[]
  source_exploded?: string[]
  source_size?: string[]
  source_function?: string[]
  source_usage_steps?: string[]
  source_storage?: string[]
  source_accessories?: string[]
  source_bundle?: string[]
  source_3d?: string[]
  source_outdoor?: string[]
  ai_generated?: string[]
  channel_versions?: Record<string, { version: string; label: string; ecommerce_main?: string[]; detail_module?: string[] }[]>
  social_media?: string[]
  social_ads?: string[]
  social_video_urls?: string[]
  ref_packaging?: string[]
  ref_manual?: string[]
  ref_certification?: string[]
  ref_dealer?: string[]
  ref_brand_style?: string[]
  ref_competitor?: string[]
  ref_archive?: string[]
  ref_banned?: string[]
}

interface PromptTemplate {
  prompts?: { prompt_name: string; prompt_type: string; prompt_text: string; version?: string }[]
}

export default function ProductCreate() {
  const navigate = useNavigate()
  const { draftId: urlDraftId, sku: editSku } = useParams<{ draftId?: string; sku?: string }>()
  
  const [loading, setLoading] = useState(false)
  const [draftId, setDraftId] = useState<string | undefined>(urlDraftId)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [notice, setNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const [sku, setSku] = useState('')
  const [barcode, setBarcode] = useState('')
  const [brand, setBrand] = useState('')
  const [series, setSeries] = useState('')
  const [nameZh, setNameZh] = useState('')
  const [nameEn, setNameEn] = useState('')
  const [listingChannel, setListingChannel] = useState<string[]>([])
  const [salesRegion, setSalesRegion] = useState<string[]>([])
  const [category, setCategory] = useState('')
  const [categoryOptions, setCategoryOptions] = useState<CategoryItem[]>([])
  const [grade, setGrade] = useState('')
  const [personInCharge, setPersonInCharge] = useState('')
  const [lifecycle, setLifecycle] = useState('')
  const [qualityNote, setQualityNote] = useState('')
  const [launchDate, setLaunchDate] = useState('')

  const [specs, setSpecs] = useState<Specs>({
    size_info: [{ label: '', value: '', unit: '厘米' }],
    capacity: [{ label: '', value: '' }],
    gross_weight_g: undefined,
    body_material: '',
    color: '',
    surface_finish: '',
    heat_source: '',
    power: '',
    technical_advantages: ['', '', ''],
    usage_instruction: ''
  })
  const [certifications, setCertifications] = useState<string[]>([])
  const CERT_OPTIONS = ['GB','FDA','FLGB','LFGB','CE','RoHS','FCC','UL','SG','KC','PSE','CCC']
  const [business, setBusiness] = useState<BusinessInfo>({
    top_selling_points: ['', '', '', '', ''],
    target_audience: '',
    positioning: '',
    price_positioning: '',
    emotional_value: '',
    usage_scenarios: [],
    competitor_benchmark: []
  })
  const [tagAudienceInput, setTagAudienceInput] = useState('')
  const [tagScenarioInput, setTagScenarioInput] = useState('')
  const [tagKeywordAInput, setTagKeywordAInput] = useState('')
  const [tagKeywordBInput, setTagKeywordBInput] = useState('')
  const [tagKeywordCInput, setTagKeywordCInput] = useState('')
  const [content, setContent] = useState<ContentAssets>({
    title_en: '',
    title_cn: '',
    long_description_en: '',
    long_description_cn: '',
    long_description_ja: '',
    bullet_points: [],
    listing_cn: '',
    listing_en: '',
    listing_ja: '',
    a_plus_content: '',
    search_keywords: []
  })
  const [media, setMedia] = useState<MediaAssets>({})
  const [lightboxImage, setLightboxImage] = useState<string | null>(null)
  const [prompt, setPrompt] = useState<PromptTemplate>({
    prompts: []
  })
  const [qaItems, setQaItems] = useState<{ question: string; answer: string; tags?: string; priority?: number }[]>([])
  const [qaNegative, setQaNegative] = useState({ high_freq_negative_words: '', response_tone: '' })
  const [openAccordion, setOpenAccordion] = useState<string | null>(null)
  const [activeChannels, setActiveChannels] = useState<string[]>(['淘宝', '京东', 'Amazon'])
  const allChannels = ['淘宝', '京东', '拼多多', '独立站', 'Amazon', 'eBay', '阿里国际站', '速卖通', '抖音', '小红书', '快手', '得物']

  useEffect(() => {
    api.categories.list().then(setCategoryOptions).catch(() => {})
  }, [])

  useEffect(() => {
    if (draftId) {
      loadDraft(draftId)
    }
  }, [draftId])

  useEffect(() => {
    if (editSku) {
      loadProduct(editSku)
    }
  }, [editSku])

  async function loadDraft(id: string) {
    setLoading(true)
    try {
      const draft = await api.drafts.get(id)
      setSku(draft.sku || '')
      setBarcode(draft.barcode || '')
      setBrand(draft.brand || '')
      setSeries(draft.series || '')
      setNameZh(draft.product_name_cn || '')
      setNameEn(draft.product_name_en || '')
      setCategory(draft.category || '')
      setGrade(draft.product_level || '')
      setPersonInCharge(draft.person_in_charge || '')
      setLifecycle(draft.lifecycle_status || '')
      setQualityNote((draft as any).quality_note || '')
      setLaunchDate(draft.launch_date || '')
      
      const specData = draft.specs_data || draft.specs || {}
      const busData = draft.business_data || draft.business || {}
      const contData = draft.content_data || draft.content || {}
      setSpecs({
        size_info: (specData as any).size_info?.length ? (specData as any).size_info : (specData as any).dimension_lines?.length ? (specData as any).dimension_lines : [{ label: '', value: '', unit: '厘米' }],
        capacity: (specData as any).capacity?.length ? (specData as any).capacity : (specData as any).capacity_lines?.length ? (specData as any).capacity_lines : [{ label: '', value: '' }],
        gross_weight_g: (specData as any).gross_weight_g ?? (specData as any).gross_weight,
        body_material: (specData as any).body_material || (specData as any).material || '',
        color: (specData as any).color || (specData as any).main_color || '',
        surface_finish: (specData as any).surface_finish || '',
        heat_source: (specData as any).heat_source || '',
        power: (specData as any).power || (specData as any).min_power || '',
        technical_advantages: (specData as any).technical_advantages || (specData as any).tech_advantages || ['', '', ''],
        usage_instruction: (specData as any).usage_instruction || (specData as any).usage_instructions || '',
      })

      setBusiness({
        top_selling_points: (busData as any).top_selling_points || (busData as any).core_selling_points || ['', '', '', '', ''],
        target_audience: (busData as any).target_audience || '',
        positioning: (busData as any).positioning || (busData as any).differentiation || '',
        price_positioning: (busData as any).price_positioning || '',
        emotional_value: (busData as any).emotional_value || '',
        usage_scenarios: (busData as any).usage_scenarios || (busData as any).use_scenarios || [],
        competitor_benchmark: (busData as any).competitor_benchmark || (busData as any).competitors || []
      })

      setContent({
        title_en: (contData as any).title_en || (contData as any).amazon_title || '',
        title_cn: (contData as any).title_cn || (contData as any).website_title || '',
        long_description_en: (contData as any).long_description_en || (contData as any).listing_en || '',
        long_description_cn: (contData as any).long_description_cn || (contData as any).listing_zh || '',
        long_description_ja: (contData as any).long_description_ja || (contData as any).listing_ja || '',
        bullet_points: (contData as any).bullet_points || (contData as any).five_bullets || [],
        listing_cn: (contData as any).listing_cn || (contData as any).listing_zh || '',
        listing_en: (contData as any).listing_en || '',
        listing_ja: (contData as any).listing_ja || '',
        a_plus_content: (contData as any).a_plus_content || '',
        search_keywords: (contData as any).search_keywords || [],
      })

      const regions = (specData as any).sales_region || []
      if (Array.isArray(regions) && regions.length > 0) setSalesRegion(regions)
      const certs = (specData as any).certifications || []
      if (Array.isArray(certs) && certs.length > 0) setCertifications(certs)
      const channels = (busData as any).listing_channel || []
      if (Array.isArray(channels) && channels.length > 0) setListingChannel(channels)
      
      const medData = draft.media_data || draft.media || {}
      setMedia(medData as MediaAssets)
      
      const promptData = draft.prompt_data || draft.prompts_data || draft.prompt || {}
      setPrompt({
        prompts: (promptData as any).prompts || (promptData as any).image_templates?.map((t: any) => ({ ...t, prompt_type: 'image' })) || []
      })
      const qaData = draft.qa_items || []
      if (Array.isArray(qaData) && qaData.length > 0) setQaItems(qaData as any)
      const negData = draft.qa_negative || null
      if (negData) setQaNegative(negData as any)
    } catch (err) {
      console.error('Failed to load draft:', err)
    } finally {
      setLoading(false)
    }
  }

  async function loadProduct(sku: string) {
    setLoading(true)
    try {
      const product = await api.products.get(sku)
      setSku(product.sku || '')
      setBarcode(product.barcode || '')
      setBrand(product.brand || '')
      setSeries(product.series || '')
      setNameZh(product.product_name_cn || '')
      setNameEn(product.product_name_en || '')
      setCategory(product.category || '')
      setGrade(product.product_level || '')
      setPersonInCharge(product.person_in_charge || '')
      setLifecycle(product.lifecycle_status || '')
      setQualityNote((product as any).quality_note || '')
      setLaunchDate(product.launch_date || '')

      const specData = product.specs || {}
      const busData = product.business || {}
      const contData = product.content || {}
      const medData = product.media || []

      setSpecs({
        size_info: (specData as any).size_info || (specData as any).dimension_lines || [{ label: '', value: '', unit: '厘米' }],
        capacity: (specData as any).capacity || (specData as any).capacity_lines || [{ label: '', value: '' }],
        gross_weight_g: (specData as any).gross_weight_g ?? (specData as any).gross_weight,
        body_material: (specData as any).body_material || (specData as any).material || '',
        color: (specData as any).color || (specData as any).main_color || '',
        surface_finish: (specData as any).surface_finish || '',
        heat_source: (specData as any).heat_source || '',
        power: (specData as any).power || '',
        technical_advantages: (specData as any).technical_advantages || (specData as any).tech_advantages || ['', '', ''],
        usage_instruction: (specData as any).usage_instruction || (specData as any).usage_instructions || '',
      })

      setBusiness({
        top_selling_points: (busData as any).top_selling_points || (busData as any).core_selling_points || ['', '', '', '', ''],
        target_audience: (busData as any).target_audience || '',
        positioning: (busData as any).positioning || (busData as any).differentiation || '',
        price_positioning: (busData as any).price_positioning || '',
        emotional_value: (busData as any).emotional_value || '',
        usage_scenarios: (busData as any).usage_scenarios || (busData as any).use_scenarios || [],
        competitor_benchmark: (busData as any).competitor_benchmark || (busData as any).competitors || []
      })

      setContent({
        title_en: (contData as any).title_en || (contData as any).amazon_title || '',
        title_cn: (contData as any).title_cn || (contData as any).website_title || '',
        long_description_en: (contData as any).long_description_en || (contData as any).listing_en || '',
        long_description_cn: (contData as any).long_description_cn || (contData as any).listing_zh || '',
        long_description_ja: (contData as any).long_description_ja || (contData as any).listing_ja || '',
        bullet_points: (contData as any).bullet_points || (contData as any).five_bullets || [],
        listing_cn: (contData as any).listing_cn || '',
        listing_en: (contData as any).listing_en || '',
        listing_ja: (contData as any).listing_ja || '',
        a_plus_content: (contData as any).a_plus_content || '',
        search_keywords: (contData as any).search_keywords || [],
      })

      setMedia(Array.isArray(medData) ? {} : medData as MediaAssets)

      const regions = (product.regions || []).map((r: any) => r.region_name || r.name || '')
      if (regions.length > 0) setSalesRegion(regions)
      const certs = (product.certifications || []).map((c: any) => c.certification_name || c.name || '')
      if (certs.length > 0) setCertifications(certs)
      const channels = (product.channels || []).map((c: any) => c.channel_name || c.name || '')
      if (channels.length > 0) setListingChannel(channels)

      const promptData = product.prompts || []
      if (promptData.length > 0) {
        setPrompt({ prompts: promptData.map((p: any) => ({
          prompt_name: p.prompt_name || p.template_name || '',
          prompt_type: p.prompt_type || 'image',
          prompt_text: p.prompt_text || '',
          version: p.version || '',
        }))})
      }
      const qaData = product.qa_items || []
      if (Array.isArray(qaData) && qaData.length > 0) setQaItems(qaData as any)
      const negData = product.qa_negative || null
      if (negData) setQaNegative(negData as any)
    } catch (err) {
      console.error('Failed to load product:', err)
    } finally {
      setLoading(false)
    }
  }

  function addDimensionLine() {
    const lines = specs.size_info || []
    setSpecs({
      ...specs,
      size_info: [...lines, { label: '', value: '', unit: '厘米' }]
    })
  }

  function updateDimensionLine(index: number, field: 'label' | 'value' | 'unit', value: string) {
    const lines = specs.size_info || []
    setSpecs({
      ...specs,
      size_info: lines.map((dim, i) =>
        i === index ? { ...dim, [field]: value } : dim
      )
    })
  }

  function removeDimensionLine(index: number) {
    const lines = specs.size_info || []
    setSpecs({
      ...specs,
      size_info: lines.filter((_, i) => i !== index)
    })
  }

  function addCapacityLine() {
    clearFieldError('capacity')
    const lines = specs.capacity || []
    setSpecs({
      ...specs,
      capacity: [...lines, { label: '', value: '' }]
    })
  }

  function updateCapacityLine(index: number, field: 'label' | 'value', value: string) {
    clearFieldError('capacity')
    const lines = specs.capacity || []
    setSpecs({
      ...specs,
      capacity: lines.map((cap, i) =>
        i === index ? { ...cap, [field]: value } : cap
      )
    })
  }

  function removeCapacityLine(index: number) {
    const lines = specs.capacity || []
    setSpecs({
      ...specs,
      capacity: lines.filter((_, i) => i !== index)
    })
  }

  function addSpecTechAdvantage() {
    clearFieldError('technical_advantages')
    const advs = specs.technical_advantages || []
    setSpecs({ ...specs, technical_advantages: [...advs, ''] })
  }

  function updateSpecTechAdvantage(index: number, value: string) {
    clearFieldError('technical_advantages')
    const advs = specs.technical_advantages || []
    setSpecs({ ...specs, technical_advantages: advs.map((a, i) => i === index ? value : a) })
  }

  function removeSpecTechAdvantage(index: number) {
    const advs = specs.technical_advantages || []
    setSpecs({ ...specs, technical_advantages: advs.filter((_, i) => i !== index) })
  }

  function addCoreSellingPoint() {
    const pts = business.top_selling_points || []
    setBusiness({ ...business, top_selling_points: [...pts, ''] })
  }

  function updateCoreSellingPoint(index: number, value: string) {
    const pts = business.top_selling_points || []
    setBusiness({ ...business, top_selling_points: pts.map((p, i) => i === index ? value : p) })
  }

  function removeCoreSellingPoint(index: number) {
    const pts = business.top_selling_points || []
    setBusiness({ ...business, top_selling_points: pts.filter((_, i) => i !== index) })
  }

  function addAudienceTag() {
    const tag = tagAudienceInput.trim()
    if (!tag) return
    const current = (business.target_audience || '').split(',').filter(Boolean)
    if (current.includes(tag)) { setTagAudienceInput(''); return }
    setBusiness({ ...business, target_audience: [...current, tag].join(',') })
    setTagAudienceInput('')
  }

  function removeAudienceTag(index: number) {
    const current = (business.target_audience || '').split(',').filter(Boolean)
    setBusiness({ ...business, target_audience: current.filter((_, i) => i !== index).join(',') })
  }

  function addScenarioTag() {
    const tag = tagScenarioInput.trim()
    if (!tag) return
    const current = business.usage_scenarios || []
    if (current.includes(tag)) { setTagScenarioInput(''); return }
    setBusiness({ ...business, usage_scenarios: [...current, tag] })
    setTagScenarioInput('')
  }

  function removeScenarioTag(index: number) {
    const current = business.usage_scenarios || []
    setBusiness({ ...business, usage_scenarios: current.filter((_, i) => i !== index) })
  }

  function addUseScenario() {
    const scenarios = business.usage_scenarios || []
    setBusiness({
      ...business,
      usage_scenarios: [...scenarios, '']
    })
  }

  function updateUseScenario(index: number, value: string) {
    const scenarios = business.usage_scenarios || []
    setBusiness({
      ...business,
      usage_scenarios: scenarios.map((s, i) => i === index ? value : s)
    })
  }

  function removeUseScenario(index: number) {
    const scenarios = business.usage_scenarios || []
    setBusiness({
      ...business,
      usage_scenarios: scenarios.filter((_, i) => i !== index)
    })
  }

  function addCompetitor() {
    const competitors = business.competitor_benchmark || []
    setBusiness({
      ...business,
      competitor_benchmark: [...competitors, { name: '', url: '' }]
    })
  }

  function updateCompetitor(index: number, value: string) {
    const competitors = business.competitor_benchmark || []
    setBusiness({
      ...business,
      competitor_benchmark: competitors.map((c, i) => i === index ? { ...c, name: value } : c)
    })
  }

  function updateCompetitorUrl(index: number, value: string) {
    const competitors = business.competitor_benchmark || []
    setBusiness({
      ...business,
      competitor_benchmark: competitors.map((c, i) => i === index ? { ...c, url: value } : c)
    })
  }

  function removeCompetitor(index: number) {
    const competitors = business.competitor_benchmark || []
    setBusiness({
      ...business,
      competitor_benchmark: competitors.filter((_, i) => i !== index)
    })
  }

  function addBullet() {
    const bullets = content.bullet_points || []
    setContent({
      ...content,
      bullet_points: [...bullets, '']
    })
  }

  function updateBullet(index: number, value: string) {
    const bullets = content.bullet_points || []
    setContent({
      ...content,
      bullet_points: bullets.map((b, i) => i === index ? value : b)
    })
  }

  function removeBullet(index: number) {
    const bullets = content.bullet_points || []
    setContent({
      ...content,
      bullet_points: bullets.filter((_, i) => i !== index)
    })
  }

  function addSearchKeyword() {
    const keywords = content.search_keywords || []
    setContent({
      ...content,
      search_keywords: [...keywords, { keyword: '', priority: 'A' }]
    })
  }

  function addKeywordTag(priority: string) {
    const inputMap: Record<string, string> = { A: tagKeywordAInput, B: tagKeywordBInput, C: tagKeywordCInput }
    const setterMap: Record<string, (v: string) => void> = { A: setTagKeywordAInput, B: setTagKeywordBInput, C: setTagKeywordCInput }
    const tag = inputMap[priority].trim()
    if (!tag) return
    const current = content.search_keywords || []
    if (current.some(k => k.keyword === tag && k.priority === priority)) { setterMap[priority](''); return }
    setContent({ ...content, search_keywords: [...current, { keyword: tag, priority }] })
    setterMap[priority]('')
  }

  function removeKeywordTag(index: number) {
    const current = content.search_keywords || []
    setContent({ ...content, search_keywords: current.filter((_, i) => i !== index) })
  }

  function getKeywordsByPriority(priority: string) {
    return (content.search_keywords || []).filter(k => k.priority === priority)
  }

  function parseMultiSelect(value: string | undefined, _default: string): string[] {
    if (!value || !value.trim()) return []
    return value.split(',').map(s => s.trim()).filter(Boolean)
  }

  function toggleArrayItem(arr: string[], setter: (v: string[]) => void, item: string) {
    if (arr.includes(item)) {
      setter(arr.filter(x => x !== item))
    } else {
      setter([...arr, item])
    }
  }

  function getMediaImages(key: string): string[] {
    return (media as any)[key] || []
  }

  function addMediaUrl(key: string) {
    const images = getMediaImages(key)
    setMedia({ ...media, [key]: [...images, ''] })
  }

  function updateMediaUrl(key: string, index: number, url: string) {
    const images = getMediaImages(key)
    setMedia({ ...media, [key]: images.map((img: string, i: number) => i === index ? url : img) })
  }

  function removeMediaUrl(key: string, index: number) {
    const images = getMediaImages(key)
    setMedia({ ...media, [key]: images.filter((_: any, i: number) => i !== index) })
  }

  async function handleMediaUpload(key: string, event: React.ChangeEvent<HTMLInputElement>) {
    const files = event.target.files
    if (!files) return
    for (const file of Array.from(files)) {
      try {
        const response = await api.uploadImage([file])
        const imageUrl = response.urls[0]
        const images = getMediaImages(key)
        setMedia({ ...media, [key]: [...images, imageUrl] })
      } catch (err) {
        console.error('Image upload failed:', err)
        showNotice('error', '图片上传失败')
      }
    }
    event.target.value = ''
  }

  function addChannelVersion(channel: string) {
    const versions = media.channel_versions || {}
    const existing = versions[channel] || []
    const maxVer = existing.reduce((max, v) => {
      const num = parseInt(v.version.replace('V', '')) || 0
      return Math.max(max, num)
    }, 0)
    const newVersion = `V${maxVer + 1}`
    setMedia({
      ...media,
      channel_versions: {
        ...versions,
        [channel]: [...existing, { version: newVersion, label: '', ecommerce_main: [], detail_module: [] }]
      }
    })
  }

  function updateChannelVersionLabel(channel: string, vi: number, label: string) {
    const versions = media.channel_versions || {}
    const existing = versions[channel] || []
    setMedia({
      ...media,
      channel_versions: {
        ...versions,
        [channel]: existing.map((v, i) => i === vi ? { ...v, label } : v)
      }
    })
  }

  function removeChannelVersion(channel: string, vi: number) {
    const versions = media.channel_versions || {}
    const existing = versions[channel] || []
    setMedia({
      ...media,
      channel_versions: {
        ...versions,
        [channel]: existing.filter((_, i) => i !== vi)
      }
    })
  }

  function getChannelVersionImages(channel: string, vi: number, type: 'ecommerce_main' | 'detail_module'): string[] {
    const versions = media.channel_versions || {}
    const existing = versions[channel] || []
    if (vi >= existing.length) return []
    return (existing[vi] as any)[type] || []
  }

  function addChannelVersionImageUrl(channel: string, vi: number, type: 'ecommerce_main' | 'detail_module') {
    const versions = media.channel_versions || {}
    const existing = versions[channel] || []
    if (vi >= existing.length) return
    const images = (existing[vi] as any)[type] || []
    setMedia({
      ...media,
      channel_versions: {
        ...versions,
        [channel]: existing.map((v, i) => i === vi ? { ...v, [type]: [...images, ''] } : v)
      }
    })
  }

  function updateChannelVersionImageUrl(channel: string, vi: number, type: 'ecommerce_main' | 'detail_module', ii: number, url: string) {
    const versions = media.channel_versions || {}
    const existing = versions[channel] || []
    if (vi >= existing.length) return
    const images = (existing[vi] as any)[type] || []
    setMedia({
      ...media,
      channel_versions: {
        ...versions,
        [channel]: existing.map((v, i) => i === vi ? { ...v, [type]: images.map((img: string, j: number) => j === ii ? url : img) } : v)
      }
    })
  }

  function removeChannelVersionImage(channel: string, vi: number, type: 'ecommerce_main' | 'detail_module', ii: number) {
    const versions = media.channel_versions || {}
    const existing = versions[channel] || []
    if (vi >= existing.length) return
    const images = (existing[vi] as any)[type] || []
    setMedia({
      ...media,
      channel_versions: {
        ...versions,
        [channel]: existing.map((v, i) => i === vi ? { ...v, [type]: images.filter((_: any, j: number) => j !== ii) } : v)
      }
    })
  }

  async function handleChannelVersionUpload(channel: string, vi: number, type: 'ecommerce_main' | 'detail_module', event: React.ChangeEvent<HTMLInputElement>) {
    const files = event.target.files
    if (!files) return
    const versions = media.channel_versions || {}
    const existing = versions[channel] || []
    if (vi >= existing.length) return
    let images = (existing[vi] as any)[type] || []
    for (const file of Array.from(files)) {
      try {
        const response = await api.uploadImage([file])
        images = [...images, response.urls[0]]
        setMedia({
          ...media,
          channel_versions: {
            ...versions,
            [channel]: existing.map((v, i) => i === vi ? { ...v, [type]: images } : v)
          }
        })
      } catch (err) {
        console.error('Image upload failed:', err)
        showNotice('error', '图片上传失败')
      }
    }
    event.target.value = ''
  }

  function getProductData() {
    const dimLines = specs.size_info || []
    const capLines = specs.capacity || []
    const sellingPoints = (business.top_selling_points || []).filter(Boolean)
    const scenarios = business.usage_scenarios || []
    const competitors = business.competitor_benchmark || []
    const bullets = content.bullet_points || []
    const keywords = content.search_keywords || []
    const specAdvs = specs.technical_advantages || []

    const hasSpecs = (dimLines.length > 0 && dimLines.some((d: any) => d.label || d.value)) ||
                     (capLines.length > 0 && capLines.some((c: any) => c.label || c.value)) ||
                     specs.gross_weight_g || specs.body_material || specs.color ||
                     specs.surface_finish || specs.heat_source || specs.power ||
                     specAdvs.some((a: string) => a.trim()) || specs.usage_instruction ||
                     certifications.length > 0
    const hasBusiness = sellingPoints.length > 0 ||
                        business.target_audience || business.positioning ||
                        business.price_positioning || business.emotional_value ||
                        scenarios.length > 0 || competitors.length > 0
    const hasContent = content.title_en || content.title_cn || bullets.length > 0 ||
                       content.listing_cn || content.listing_en || content.listing_ja ||
                       content.long_description_en || content.long_description_cn || content.long_description_ja ||
                       content.a_plus_content || keywords.length > 0
    const hasMedia = Object.keys(media).filter(k => k !== 'channel_versions' || Object.keys(media.channel_versions || {}).length > 0).length > 0
    const hasPrompt = (prompt.prompts || []).length > 0

    return {
      sku,
      barcode: barcode || undefined,
      brand: brand || undefined,
      series: series || undefined,
      product_name_cn: nameZh || undefined,
      product_name_en: nameEn || undefined,
      category: category || undefined,
      product_level: grade || undefined,
      person_in_charge: personInCharge || undefined,
      lifecycle_status: lifecycle || undefined,
      quality_note: qualityNote || undefined,
      launch_date: launchDate || undefined,
      specs_data: {
        ...specs,
        sales_region: salesRegion,
        certifications,
      } as any,
      business_data: {
        ...business,
        listing_channel: listingChannel,
      },
      content_data: hasContent ? content : undefined,
      media_data: hasMedia ? media : undefined,
      prompts_data: hasPrompt ? (prompt.prompts || []) : undefined,
      qa_items: qaItems.length > 0 ? qaItems : undefined,
      qa_negative: (qaNegative.high_freq_negative_words || qaNegative.response_tone) ? qaNegative : undefined,
    }
  }

  function addPromptTemplate() {
    const templates = prompt.prompts || []
    setPrompt({ prompts: [...templates, { prompt_name: '', prompt_type: 'image', prompt_text: '', version: '' }] })
  }

  function updatePromptTemplate(index: number, field: 'prompt_name' | 'prompt_type' | 'prompt_text' | 'version', value: string) {
    const templates = prompt.prompts || []
    setPrompt({
      prompts: templates.map((p, i) => i === index ? { ...p, [field]: value } : p)
    })
  }

  function removePromptTemplate(index: number) {
    const templates = prompt.prompts || []
    setPrompt({ prompts: templates.filter((_, i) => i !== index) })
  }

  function showNotice(type: 'success' | 'error', text: string) {
    setNotice({ type, text })
    window.setTimeout(() => setNotice(null), 3500)
  }

  async function handleSave() {
    if (!sku.trim()) {
      showNotice('error', '请输入 SKU')
      return
    }

    setLoading(true)
    try {
      const data = getProductData()
      
      if (draftId) {
        await api.drafts.update(draftId, data)
      } else {
        const created = await api.drafts.create(data)
        const params = new URLSearchParams(window.location.search)
        params.set('draftId', created.id)
        window.history.replaceState(null, '', `${window.location.pathname}?${params.toString()}`)
        setDraftId(created.id as any)
      }
      
      showNotice('success', '草稿保存成功')
    } catch (err: any) {
      console.error('Save draft failed:', err)
      showNotice('error', err?.message || '保存失败，请重试')
    } finally {
      setLoading(false)
    }
  }

  // field-id → label mapping for scroll targeting
  const FIELD_IDS: Record<string, string> = {
    barcode: '条形码', nameZh: '商品中文名称',
    brand: '品牌',
    body_material: '主体材质', color: '主色系', surface_finish: '表面处理',
    heat_source: '适用热源', capacity: '容量', power: '功率',
    technical_advantages: '技术优势', usage_instruction: '使用说明',
    title_cn: '标题中文', long_description_cn: '中文长描述',
  }
  function validateRequired(): string[] {
    const missing: string[] = []
    if (!sku.trim()) missing.push('sku')
    if (!barcode.trim()) missing.push('barcode')
    if (!nameZh.trim()) missing.push('nameZh')
    if (!brand.trim()) missing.push('brand')
    if (!specs.body_material?.trim()) missing.push('body_material')
    if (!specs.color?.trim()) missing.push('color')
    if (!specs.surface_finish?.trim()) missing.push('surface_finish')
    if (!specs.heat_source?.trim()) missing.push('heat_source')
    if (!specs.capacity || (Array.isArray(specs.capacity) && specs.capacity.every((c: any) => !c.label?.trim() && !c.value?.trim()))) missing.push('capacity')
    if (!specs.power?.trim()) missing.push('power')
    if (!specs.technical_advantages || (Array.isArray(specs.technical_advantages) && specs.technical_advantages.every((t: any) => !t?.trim()))) missing.push('technical_advantages')
    if (!specs.usage_instruction?.trim()) missing.push('usage_instruction')
    if (!content.title_cn?.trim()) missing.push('title_cn')
    if (!content.long_description_cn?.trim()) missing.push('long_description_cn')
    return missing
  }

  function scrollToFirstError(missing: string[]) {
    const first = missing[0]
    const el = document.getElementById('field-' + first)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      el.classList.add('ring-2', 'ring-red-400')
      setTimeout(() => el.classList.remove('ring-2', 'ring-red-400'), 3000)
    }
    const errs: Record<string, string> = {}
    missing.forEach(f => { errs[f] = FIELD_IDS[f] || f })
    setFieldErrors(errs)
  }

  function clearFieldError(field: string) {
    if (fieldErrors[field]) {
      const next = { ...fieldErrors }
      delete next[field]
      setFieldErrors(next)
    }
  }

  async function handlePublish() {
    const missing = validateRequired()
    if (missing.length > 0) {
      scrollToFirstError(missing)
      return
    }

    setLoading(true)
    try {
      let activeDraftId = draftId

      // Always save to draft first, then publish. This ensures M2M data is synced.
      const data = getProductData()
      if (activeDraftId) {
        await api.drafts.update(activeDraftId, data)
      } else {
        const created = await api.drafts.create(data)
        activeDraftId = created.id
        const params = new URLSearchParams(window.location.search)
        params.set('draftId', created.id)
        window.history.replaceState(null, '', `${window.location.pathname}?${params.toString()}`)
        setDraftId(created.id as any)
      }

      await api.drafts.publish(activeDraftId)

      showNotice('success', '发布成功')
      navigate('/products')
    } catch (err: any) {
      console.error('Publish failed:', err)
      showNotice('error', err?.message || '发布失败，请重试')
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
      </div>
    )
  }

  return (
    <div className="p-4 max-w-4xl mx-auto">
      <button onClick={() => navigate(draftId ? '/products/drafts' : '/products')} className="text-sm text-blue-500 hover:text-blue-700 mb-2 flex items-center gap-1">
        ← {draftId ? '返回草稿箱' : '返回产品管理'}
      </button>
      {notice && (
        <div className={`mb-4 rounded-xl border px-4 py-3 text-sm ${
          notice.type === 'success'
            ? 'border-green-200 bg-green-50 text-green-700'
            : 'border-red-200 bg-red-50 text-red-700'
        }`}>
          {notice.text}
        </div>
      )}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-apple-text tracking-tight">
            {editSku ? '编辑产品' : draftId ? '编辑产品草稿' : '+ 新增产品'}
          </h1>
          <p className="text-sm text-apple-text mt-1">
            {editSku ? '编辑已发布的产品' : draftId ? '编辑已保存的草稿' : '创建新产品'}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={handleSave}
            disabled={loading}
            className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-200 transition-colors disabled:opacity-50">
            {loading ? '保存中...' : '保存草稿'}
          </button>
          <button onClick={handlePublish}
            disabled={loading}
            className="px-4 py-2 bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 transition-colors disabled:opacity-50">
            {loading ? '发布中...' : '🚀 发布产品'}
          </button>
        </div>
      </div>

      <div className="space-y-6">
        <div className="glass rounded-xl p-6">
          <h2 className="text-lg font-semibold text-apple-text mb-4">📋 L1 - 产品身份层</h2>

          <div className="grid grid-cols-2 gap-3 mb-4">
            <div>
              <label className="block text-sm text-apple-text mb-1">SKU *</label>
              <input type="text" value={sku} onChange={(e) => setSku(e.target.value)}
                className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
                placeholder="产品唯一标识" />
            </div>
            <div>
              <label className="block text-sm text-apple-text mb-1">条形码 *</label>
              <input id="field-barcode" type="text" value={barcode} onChange={(e) => { setBarcode(e.target.value); clearFieldError('barcode') }}
                className={`w-full px-3 py-2 bg-white/50 border rounded-lg text-sm focus:outline-none focus:border-blue-400 ${fieldErrors.barcode ? 'border-red-400 bg-red-50' : 'border-gray-200'}`} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 mb-4">
            <div>
              <label className="block text-sm text-apple-text mb-1">商品中文名称 *</label>
              <input id="field-nameZh" type="text" value={nameZh} onChange={(e) => { setNameZh(e.target.value); clearFieldError('nameZh') }}
                className={`w-full px-3 py-2 bg-white/50 border rounded-lg text-sm focus:outline-none focus:border-blue-400 ${fieldErrors.nameZh ? 'border-red-400 bg-red-50' : 'border-gray-200'}`} />
            </div>
            <div>
              <label className="block text-sm text-apple-text mb-1">商品英文名称 *</label>
              <input id="field-nameEn" type="text" value={nameEn} onChange={(e) => { setNameEn(e.target.value); clearFieldError('nameEn') }}
                className={`w-full px-3 py-2 bg-white/50 border rounded-lg text-sm focus:outline-none focus:border-blue-400 ${fieldErrors.nameEn ? 'border-red-400 bg-red-50' : 'border-gray-200'}`} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 mb-4">
            <div>
              <label className="block text-sm text-apple-text mb-1">上架渠道</label>
              <div className="flex flex-wrap gap-2">
                {['淘宝','京东','拼多多','独立站','Amazon','eBay','阿里国际站','速卖通','抖音','小红书','快手','得物'].map(ch => (
                  <label key={ch} className={`px-3 py-1.5 rounded-full text-xs cursor-pointer border transition-colors ${
                    listingChannel.includes(ch) ? 'bg-blue-500 text-white border-blue-500' : 'bg-white/50 text-apple-gray-dark border-gray-200 hover:border-blue-300'
                  }`}>
                    <input type="checkbox" className="hidden" checked={listingChannel.includes(ch)}
                      onChange={() => toggleArrayItem(listingChannel, setListingChannel, ch)} />
                    {ch}
                  </label>
                ))}
              </div>
            </div>
            <div>
              <label className="block text-sm text-apple-text mb-1">售卖地区</label>
              <div className="flex flex-wrap gap-2">
                {['国内','美国','日本','欧洲'].map(region => (
                  <label key={region} className={`px-3 py-1.5 rounded-full text-xs cursor-pointer border transition-colors ${
                    salesRegion.includes(region) ? 'bg-blue-500 text-white border-blue-500' : 'bg-white/50 text-apple-gray-dark border-gray-200 hover:border-blue-300'
                  }`}>
                    <input type="checkbox" className="hidden" checked={salesRegion.includes(region)}
                      onChange={() => toggleArrayItem(salesRegion, setSalesRegion, region)} />
                    {region}
                  </label>
                ))}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 mb-4">
            <div>
              <label className="block text-sm text-apple-text mb-1">品牌 *</label>
              <input id="field-brand" type="text" value={brand} onChange={(e) => { setBrand(e.target.value); clearFieldError('brand') }}
                className={`w-full px-3 py-2 bg-white/50 border rounded-lg text-sm focus:outline-none focus:border-blue-400 ${fieldErrors.brand ? 'border-red-400 bg-red-50' : 'border-gray-200'}`} />
            </div>
            <div>
              <label className="block text-sm text-apple-text mb-1">系列</label>
              <input type="text" value={series} onChange={(e) => setSeries(e.target.value)}
                className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400" />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 mb-4">
            <div>
              <label className="block text-sm text-apple-text mb-1">系统分类</label>
              <select value={category} onChange={(e) => setCategory(e.target.value)}
                className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400">
                <option value="">请选择系统分类</option>
                {categoryOptions.map(cat => (
                  <option key={cat.id} value={cat.category_name}>{cat.category_name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm text-apple-text mb-1">商品分级</label>
              <select value={grade} onChange={(e) => setGrade(e.target.value)}
                className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400">
                <option value="">请选择商品分级</option>
                <option value="A类品">A类品</option>
                <option value="B类品">B类品</option>
                <option value="C类品">C类品</option>
                <option value="D类品">D类品</option>
                <option value="E类品">E类品</option>
                <option value="金波专属">金波专属</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 mb-4">
            <div>
              <label className="block text-sm text-apple-text mb-1">上市时间</label>
              <input type="date" value={launchDate} onChange={(e) => setLaunchDate(e.target.value)}
                className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400" />
            </div>
            <div>
              <label className="block text-sm text-apple-text mb-1">生命周期</label>
              <select value={lifecycle} onChange={(e) => setLifecycle(e.target.value)}
                className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400">
                <option value="">选择状态</option>
                <option value="未上市新品">未上市新品</option>
                <option value="新品">新品</option>
                <option value="常规品">常规品</option>
                <option value="主推品">主推品</option>
                <option value="主推新品">主推新品</option>
                <option value="非主推新品">非主推新品</option>
                <option value="清仓品">清仓品</option>
                <option value="老款无货不补">老款无货不补</option>
                <option value="已无货不补">已无货不补</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-sm text-apple-text mb-1">负责人 *</label>
            <input id="field-personInCharge" type="text" value={personInCharge} onChange={(e) => { setPersonInCharge(e.target.value); clearFieldError('personInCharge') }}
              className={`w-48 px-3 py-2 bg-white/50 border rounded-lg text-sm focus:outline-none focus:border-blue-400 ${fieldErrors.personInCharge ? 'border-red-400 bg-red-50' : 'border-gray-200'}`} />
          </div>
          <div className="mt-4">
            <label className="block text-sm text-apple-text mb-1">品质情况</label>
            <textarea
              value={qualityNote}
              onChange={(e) => setQualityNote(e.target.value)}
              className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
              rows={3}
              placeholder="例如：外箱轻微坏损、锅体划痕、配件缺失、抽检正常"
            />
          </div>
        </div>

        <div className="glass rounded-xl p-6">
          <h2 className="text-lg font-semibold text-apple-text mb-4">📐 L2 - 物理规格层</h2>
          
          <div className="mb-6">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-medium text-apple-text">尺寸信息</span>
              <button onClick={addDimensionLine} className="text-sm text-blue-600 hover:text-blue-700">
                + 添加尺寸
              </button>
            </div>
            <div className="space-y-3">
              {(specs.size_info || []).map((dim, i) => (
                <div key={i} className="flex items-center gap-3">
                  <input type="text" value={dim.label} onChange={(e) => updateDimensionLine(i, 'label', e.target.value)}
                    className="flex-1 px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
                    placeholder="形态（展开尺寸/折叠尺寸/直径/长/宽/高）" />
                  <input type="text" value={dim.value} onChange={(e) => updateDimensionLine(i, 'value', e.target.value)}
                    className="flex-1 px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
                    placeholder="数值" />
                  <select value={dim.unit} onChange={(e) => updateDimensionLine(i, 'unit', e.target.value)}
                    className="w-20 px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400">
                    <option value="厘米">厘米</option>
                    <option value="毫米">毫米</option>
                    <option value="英寸">英寸</option>
                  </select>
                  <button onClick={() => removeDimensionLine(i)} className="text-red-500 hover:text-red-700">✕</button>
                </div>
              ))}
            </div>
          </div>

          <div id="field-capacity" className="mb-6">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-medium text-apple-text">容量信息</span>
              <button onClick={addCapacityLine} className="text-sm text-blue-600 hover:text-blue-700">
                + 添加容量
              </button>
            </div>
            <div className="space-y-3">
              {(specs.capacity || []).map((cap, i) => (
                <div key={i} className="flex items-center gap-3">
                  <input type="text" value={cap.label} onChange={(e) => updateCapacityLine(i, 'label', e.target.value)}
                    className="flex-1 px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
                    placeholder="大锅/小锅" />
                  <input type="text" value={cap.value} onChange={(e) => updateCapacityLine(i, 'value', e.target.value)}
                    className="flex-1 px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
                    placeholder="3L/1.5L" />
                  <button onClick={() => removeCapacityLine(i)} className="text-red-500 hover:text-red-700">✕</button>
                </div>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4 mb-6">
            <div>
              <label className="block text-sm text-apple-text mb-1">毛重 (g)</label>
              <input type="number" value={specs.gross_weight_g || ''} onChange={(e) => setSpecs({ ...specs, gross_weight_g: parseFloat(e.target.value) || undefined })}
                className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400" />
            </div>
            <div>
              <label className="block text-sm text-apple-text mb-1">主体材质 *</label>
              <input id="field-body_material" type="text" value={specs.body_material} onChange={(e) => { setSpecs({ ...specs, body_material: e.target.value }); clearFieldError('body_material') }}
                className={`w-full px-3 py-2 bg-white/50 border rounded-lg text-sm focus:outline-none focus:border-blue-400 ${fieldErrors.body_material ? 'border-red-400 bg-red-50' : 'border-gray-200'}`} />
            </div>
            <div>
              <label className="block text-sm text-apple-text mb-1">主色系 *</label>
              <input id="field-color" type="text" value={specs.color || ''} onChange={(e) => { setSpecs({ ...specs, color: e.target.value }); clearFieldError('color') }}
                className={`w-full px-3 py-2 bg-white/50 border rounded-lg text-sm focus:outline-none focus:border-blue-400 ${fieldErrors.color ? 'border-red-400 bg-red-50' : 'border-gray-200'}`} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4 mb-6">
            <div>
              <label className="block text-sm text-apple-text mb-1">表面处理 *</label>
              <input id="field-surface_finish" type="text" value={specs.surface_finish} onChange={(e) => { setSpecs({ ...specs, surface_finish: e.target.value }); clearFieldError('surface_finish') }}
                className={`w-full px-3 py-2 bg-white/50 border rounded-lg text-sm focus:outline-none focus:border-blue-400 ${fieldErrors.surface_finish ? 'border-red-400 bg-red-50' : 'border-gray-200'}`}
                placeholder="喷涂/氧化/电镀" />
            </div>
            <div>
              <label className="block text-sm text-apple-text mb-1">适用热源 *</label>
              <input id="field-heat_source" type="text" value={specs.heat_source || ''} onChange={(e) => { setSpecs({ ...specs, heat_source: e.target.value }); clearFieldError('heat_source') }}
                className={`w-full px-3 py-2 bg-white/50 border rounded-lg text-sm focus:outline-none focus:border-blue-400 ${fieldErrors.heat_source ? 'border-red-400 bg-red-50' : 'border-gray-200'}`}
                placeholder="电磁炉/燃气灶" />
            </div>
          </div>

          <div className="mb-6">
            <label className="block text-sm text-apple-text mb-2">认证信息</label>
            <div className="flex flex-wrap gap-2">
              {CERT_OPTIONS.map(cert => (
                <label key={cert} className={`px-3 py-1.5 rounded-full text-xs cursor-pointer border transition-colors ${
                  certifications.includes(cert) ? 'bg-blue-500 text-white border-blue-500' : 'bg-white/50 text-apple-gray-dark border-gray-200 hover:border-blue-300'
                }`}>
                  <input type="checkbox" className="hidden" checked={certifications.includes(cert)}
                    onChange={() => toggleArrayItem(certifications, setCertifications, cert)} />
                  {cert}
                </label>
              ))}
            </div>
          </div>

          <div className="mb-6">
            <div>
              <label className="block text-sm text-apple-text mb-1">功率（炉具类）</label>
              <input id="field-power" type="text" value={specs.power || ''} onChange={(e) => { setSpecs({ ...specs, power: e.target.value }); clearFieldError('power') }}
                className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
                placeholder="800W-2000W" />
            </div>
          </div>

          <div id="field-technical_advantages" className="mb-6">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-medium text-apple-text">技术优势</span>
              <button onClick={addSpecTechAdvantage} className="text-sm text-blue-600 hover:text-blue-700">+ 添加</button>
            </div>
            <div className="space-y-2">
              {(specs.technical_advantages || []).map((ta, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="text-sm text-apple-text w-6">{i + 1}.</span>
                  <input type="text" value={ta} onChange={(e) => updateSpecTechAdvantage(i, e.target.value)}
                    className="flex-1 px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
                    placeholder="技术优势描述" />
                  <button onClick={() => removeSpecTechAdvantage(i)} className="text-red-500 hover:text-red-700">✕</button>
                </div>
              ))}
            </div>
          </div>

          <div className="mb-6 mt-6">
            <label className="block text-sm text-apple-text mb-1">使用说明</label>
            <textarea id="field-usage_instruction" value={specs.usage_instruction || ''} onChange={(e) => { setSpecs({ ...specs, usage_instruction: e.target.value }); clearFieldError('usage_instruction') }}
              className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
              rows={3} placeholder="首次使用前请清洗..." />
          </div>
        </div>

        <div className="glass rounded-xl p-6">
          <h2 className="text-lg font-semibold text-apple-text mb-4">💼 L3 - 商业价值层</h2>
          
          <div className="mb-4">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-medium text-apple-text">核心卖点 TOP5</span>
              <button onClick={addCoreSellingPoint} className="text-sm text-blue-600 hover:text-blue-700">+ 添加</button>
            </div>
            <div className="space-y-2">
              {(business.top_selling_points || []).map((pt, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="text-sm text-apple-text w-6">{i + 1}.</span>
                  <input type="text" value={pt} onChange={(e) => updateCoreSellingPoint(i, e.target.value)}
                    className="flex-1 px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
                    placeholder="核心卖点描述" />
                  <button onClick={() => removeCoreSellingPoint(i)} className="text-red-500 hover:text-red-700">✕</button>
                </div>
              ))}
            </div>
          </div>

          <div className="mb-4">
            <label className="block text-sm text-apple-text mb-1">目标人群</label>
            <div className="flex gap-2">
              <input type="text" value={tagAudienceInput} onChange={(e) => setTagAudienceInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), addAudienceTag())}
                className="flex-1 px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
                placeholder="输入后回车或点击添加" />
              <button onClick={addAudienceTag} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">添加</button>
            </div>
            {(business.target_audience || '').split(',').filter(Boolean).length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {(business.target_audience || '').split(',').filter(Boolean).map((tag, i) => (
                  <span key={i} className="inline-flex items-center gap-1 px-2.5 py-1 bg-blue-50 text-blue-700 rounded-full text-xs">
                    {tag}
                    <button onClick={() => removeAudienceTag(i)} className="text-blue-400 hover:text-blue-600 ml-0.5">✕</button>
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="mb-4">
            <label className="block text-sm text-apple-text mb-1">差异化定位</label>
            <input type="text" value={business.positioning || ''} onChange={(e) => setBusiness({ ...business, positioning: e.target.value })}
              className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
              placeholder="市面上最轻的钛合金炊具套装" />
          </div>

          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-sm text-apple-text mb-1">价格定位带</label>
              <select value={business.price_positioning || ''} onChange={(e) => setBusiness({ ...business, price_positioning: e.target.value })}
                className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400">
                <option value="">请选择</option>
                <option value="入门款">入门款</option>
                <option value="中端">中端</option>
                <option value="高端">高端</option>
              </select>
            </div>
            <div>
              <label className="block text-sm text-apple-text mb-1">情感价值</label>
              <input type="text" value={business.emotional_value || ''} onChange={(e) => setBusiness({ ...business, emotional_value: e.target.value })}
                className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
                placeholder="家庭温馨、健康生活方式的象征" />
            </div>
          </div>

          <div className="mb-4">
            <label className="block text-sm text-apple-text mb-1">使用场景</label>
            <div className="flex gap-2">
              <input type="text" value={tagScenarioInput} onChange={(e) => setTagScenarioInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), addScenarioTag())}
                className="flex-1 px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
                placeholder="输入后回车或点击添加" />
              <button onClick={addScenarioTag} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">添加</button>
            </div>
            {(business.usage_scenarios || []).length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {(business.usage_scenarios || []).map((tag, i) => (
                  <span key={i} className="inline-flex items-center gap-1 px-2.5 py-1 bg-green-50 text-green-700 rounded-full text-xs">
                    {tag}
                    <button onClick={() => removeScenarioTag(i)} className="text-green-400 hover:text-green-600 ml-0.5">✕</button>
                  </span>
                ))}
              </div>
            )}
          </div>

          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-medium text-apple-text">竞品对标</span>
              <button onClick={addCompetitor} className="text-sm text-blue-600 hover:text-blue-700">+ 添加</button>
            </div>
            <div className="space-y-2">
              {(business.competitor_benchmark || []).map((comp, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="text-sm text-apple-text w-6">{i + 1}.</span>
                  <input type="text" value={comp.name} onChange={(e) => updateCompetitor(i, e.target.value)}
                    className="flex-1 px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
                    placeholder="竞品名称" />
                  <input type="text" value={comp.url || ''} onChange={(e) => updateCompetitorUrl(i, e.target.value)}
                    className="flex-1 px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
                    placeholder="链接 (选填)" />
                  <button onClick={() => removeCompetitor(i)} className="text-red-500 hover:text-red-700">✕</button>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="glass rounded-xl p-6">
          <h2 className="text-lg font-semibold text-apple-text mb-4">📝 L4 - 内容素材层</h2>

          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-sm text-apple-text mb-1">标题（英文） *</label>
              <input id="field-title_en" type="text" value={content.title_en || ''} onChange={(e) => { setContent({ ...content, title_en: e.target.value }); clearFieldError('title_en') }}
                className={`w-full px-3 py-2 bg-white/50 border rounded-lg text-sm focus:outline-none focus:border-blue-400 ${fieldErrors.title_en ? 'border-red-400 bg-red-50' : 'border-gray-200'}`}
                placeholder="Product Title" />
            </div>
            <div>
              <label className="block text-sm text-apple-text mb-1">标题（中文） *</label>
              <input id="field-title_cn" type="text" value={content.title_cn || ''} onChange={(e) => { setContent({ ...content, title_cn: e.target.value }); clearFieldError('title_cn') }}
                className={`w-full px-3 py-2 bg-white/50 border rounded-lg text-sm focus:outline-none focus:border-blue-400 ${fieldErrors.title_cn ? 'border-red-400 bg-red-50' : 'border-gray-200'}`}
                placeholder="产品标题" />
            </div>
          </div>

          <div className="mb-4">
            <label className="block text-sm text-apple-text mb-1">产品长描述（英文） *</label>
            <textarea id="field-long_description_en" value={content.long_description_en || ''} onChange={(e) => { setContent({ ...content, long_description_en: e.target.value }); clearFieldError('long_description_en') }}
              className={`w-full px-3 py-2 bg-white/50 border rounded-lg text-sm focus:outline-none focus:border-blue-400 ${fieldErrors.long_description_en ? 'border-red-400 bg-red-50' : 'border-gray-200'}`}
              rows={4} placeholder="Detailed product description in English..." />
          </div>

          <div className="mb-4">
            <label className="block text-sm text-apple-text mb-1">产品长描述（中文） *</label>
            <textarea id="field-long_description_cn" value={content.long_description_cn || ''} onChange={(e) => { setContent({ ...content, long_description_cn: e.target.value }); clearFieldError('long_description_cn') }}
              className={`w-full px-3 py-2 bg-white/50 border rounded-lg text-sm focus:outline-none focus:border-blue-400 ${fieldErrors.long_description_cn ? 'border-red-400 bg-red-50' : 'border-gray-200'}`}
              rows={4} placeholder="产品详细描述..." />
          </div>

          <div className="mb-4">
            <label className="block text-sm text-apple-text mb-1">搜索关键词库</label>

            {(['A', 'B', 'C'] as const).map(priority => {
              const inputMap: Record<string, string> = { A: tagKeywordAInput, B: tagKeywordBInput, C: tagKeywordCInput }
              const setterMap: Record<string, (v: string) => void> = { A: setTagKeywordAInput, B: setTagKeywordBInput, C: setTagKeywordCInput }
              const colorMap: Record<string, string> = {
                A: 'bg-red-50 text-red-700 border-red-200',
                B: 'bg-amber-50 text-amber-700 border-amber-200',
                C: 'bg-green-50 text-green-700 border-green-200',
              }
              const btnMap: Record<string, string> = {
                A: 'bg-red-500 hover:bg-red-600',
                B: 'bg-amber-500 hover:bg-amber-600',
                C: 'bg-green-500 hover:bg-green-600',
              }
              const keywords = getKeywordsByPriority(priority)
              return (
                <div key={priority} className="mb-3">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className={`text-xs font-semibold px-2 py-0.5 rounded ${priority === 'A' ? 'bg-red-100 text-red-700' : priority === 'B' ? 'bg-amber-100 text-amber-700' : 'bg-green-100 text-green-700'}`}>
                      {priority}级
                    </span>
                    <span className="text-xs text-apple-text">
                      {priority === 'A' ? '高优先级 / 核心词' : priority === 'B' ? '中等优先级 / 扩展词' : '泛匹配 / 补充词'}
                    </span>
                  </div>
                  {(keywords.length > 0) && (
                    <div className="flex flex-wrap gap-1.5 mb-1.5">
                      {keywords.map((kw, i) => {
                        const globalIndex = (content.search_keywords || []).findIndex(k => k.keyword === kw.keyword && k.priority === priority)
                        return (
                          <span key={i} className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs border ${colorMap[priority]}`}>
                            {kw.keyword}
                            <button onClick={() => removeKeywordTag(globalIndex)} className="opacity-50 hover:opacity-100 ml-0.5">✕</button>
                          </span>
                        )
                      })}
                    </div>
                  )}
                  <div className="flex gap-2">
                    <input type="text" value={inputMap[priority]} onChange={(e) => setterMap[priority](e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), addKeywordTag(priority))}
                      className={`flex-1 px-3 py-1.5 bg-white/50 border border-gray-200 rounded-lg text-xs focus:outline-none focus:border-blue-400`}
                      placeholder={`添加 ${priority} 级关键词...`} />
                    <button onClick={() => addKeywordTag(priority)}
                      className={`px-3 py-1.5 text-white rounded-lg text-xs font-medium ${btnMap[priority]}`}>
                      添加
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        <div className="glass rounded-xl p-6">
          <h2 className="text-lg font-semibold text-apple-text mb-4">📚 L5 - 知识库层</h2>

          <div className="mb-4">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-medium text-apple-text">常见问题 Q&A</span>
              <button onClick={() => setQaItems([...qaItems, { question: '', answer: '', priority: 0 }])} className="text-sm text-blue-600 hover:text-blue-700">+ 添加问答</button>
            </div>
            {qaItems.length === 0 && (
              <p className="text-sm text-apple-gray-medium py-4 text-center">暂无问答，点击上方按钮添加</p>
            )}
            <div className="space-y-3">
              {qaItems.map((qa, i) => (
                <div key={i} className="bg-white/50 rounded-lg p-3 border border-gray-200">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-medium text-apple-text">Q{i + 1}</span>
                    <button onClick={() => setQaItems(qaItems.filter((_, j) => j !== i))} className="text-red-500 hover:text-red-700 text-xs">删除</button>
                  </div>
                  <input type="text" value={qa.question} onChange={(e) => {
                    const next = [...qaItems]; next[i] = { ...next[i], question: e.target.value }; setQaItems(next)
                  }} placeholder="问题" className="w-full px-3 py-2 bg-white border border-gray-200 rounded-lg text-sm mb-2 focus:outline-none focus:border-blue-400" />
                  <textarea value={qa.answer} onChange={(e) => {
                    const next = [...qaItems]; next[i] = { ...next[i], answer: e.target.value }; setQaItems(next)
                  }} placeholder="标准答案" className="w-full px-3 py-2 bg-white border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400" rows={2} />
                </div>
              ))}
            </div>
          </div>

          <div className="border-t border-gray-200 pt-4">
            <span className="text-sm font-medium text-apple-text mb-3 block">差评应对话术</span>
            <div className="grid grid-cols-1 gap-3">
              <div>
                <label className="block text-xs text-apple-gray-medium mb-1">差评高频词</label>
                <input type="text" value={qaNegative.high_freq_negative_words} onChange={(e) => setQaNegative({ ...qaNegative, high_freq_negative_words: e.target.value })}
                  className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
                  placeholder="如：太重、太大、刮花" />
              </div>
              <div>
                <label className="block text-xs text-apple-gray-medium mb-1">应对话术</label>
                <textarea value={qaNegative.response_tone} onChange={(e) => setQaNegative({ ...qaNegative, response_tone: e.target.value })}
                  className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
                  rows={2} placeholder="客服应对建议..." />
              </div>
            </div>
          </div>
        </div>

        <div className="glass rounded-xl p-6">
          <h2 className="text-lg font-semibold text-apple-text mb-4">🖼️ L6 - 多媒体资产层</h2>

          {([
            { id: 'source', icon: '📦', title: '原始素材层', fields: [
              { key: 'source_white_bg', label: '产品白底图' },
              { key: 'source_multi_angle', label: '产品多角度图' },
              { key: 'source_structure', label: '产品结构图' },
              { key: 'source_exploded', label: '产品爆炸图' },
              { key: 'source_size', label: '产品尺寸图' },
              { key: 'source_function', label: '功能示意图' },
              { key: 'source_usage_steps', label: '使用步骤图' },
              { key: 'source_storage', label: '收纳图' },
              { key: 'source_accessories', label: '配件图' },
              { key: 'source_bundle', label: '套装图' },
              { key: 'source_3d', label: '3D 渲染图' },
              { key: 'source_outdoor', label: '户外场景图' },
            ]},
            { id: 'ai', icon: '🤖', title: 'AI层', fields: [
              { key: 'ai_generated', label: 'AI 生成图' },
            ]},
            { id: 'channel', icon: '🏪', title: '渠道层', isChannel: true },
            { id: 'social', icon: '📱', title: '社媒层', fields: [
              { key: 'social_media', label: '社媒传播图' },
              { key: 'social_ads', label: '广告投放图' },
              { key: 'social_video_urls', label: '视频素材', isVideo: true },
            ]},
            { id: 'ref', icon: '🗂️', title: '参考辅助层', fields: [
              { key: 'ref_packaging', label: '包装图' },
              { key: 'ref_manual', label: '说明书插图' },
              { key: 'ref_certification', label: '认证/测试图' },
              { key: 'ref_dealer', label: '经销商素材' },
              { key: 'ref_brand_style', label: '品牌风格参考图' },
              { key: 'ref_competitor', label: '竞品参考图' },
              { key: 'ref_archive', label: '历史归档图' },
              { key: 'ref_banned', label: '禁用素材' },
            ]},
          ] as const).map(section => (
            <div key={section.id} className="border border-gray-200 rounded-xl overflow-hidden mb-3">
              <button
                onClick={() => setOpenAccordion(openAccordion === section.id ? null : section.id)}
                className="w-full flex items-center justify-between px-4 py-2.5 bg-gray-50 hover:bg-gray-100 transition-colors"
              >
                <span className="text-sm font-semibold text-apple-text">{section.icon} {section.title}</span>
                <span className={`text-xs text-gray-400 transition-transform duration-200 ${openAccordion === section.id ? 'rotate-180' : ''}`}>▼</span>
              </button>
              {openAccordion === section.id && (
                <div className="px-4 py-3 space-y-3">
                  {'isChannel' in section && section.isChannel ? (
                    <div className="space-y-4">
                      {activeChannels.map(ch => {
                        const versions = media.channel_versions?.[ch] || []
                        return (
                          <div key={ch} className="bg-white/60 rounded-lg p-3 border border-gray-100">
                            <div className="flex items-center justify-between mb-2">
                              <div className="flex items-center gap-2">
                                <button onClick={() => {
                                  setActiveChannels(activeChannels.filter(c => c !== ch))
                                  const versions = media.channel_versions || {}
                                  const rest = { ...versions }
                                  delete rest[ch]
                                  setMedia({ ...media, channel_versions: rest })
                                }}
                                  className="text-red-400 hover:text-red-600 text-xs font-bold" title="删除渠道">✕</button>
                                <span className="text-sm font-medium text-apple-text">{ch}</span>
                              </div>
                              <button onClick={() => addChannelVersion(ch)}
                                className="text-xs text-blue-600 hover:text-blue-700 font-medium">
                                + 新版本
                              </button>
                            </div>
                            {versions.length === 0 ? (
                              <p className="text-xs text-apple-text">暂无版本，点击"+ 新版本"添加</p>
                            ) : (
                              <div className="space-y-3">
                                {versions.map((v, vi) => (
                                  <div key={vi} className="bg-gray-50 rounded-lg p-3">
                                    <div className="flex items-center gap-3 mb-2">
                                      <span className="text-xs font-bold text-blue-700 bg-blue-100 px-2 py-0.5 rounded">{v.version}</span>
                                      <input
                                        type="text"
                                        value={v.label}
                                        onChange={(e) => updateChannelVersionLabel(ch, vi, e.target.value)}
                                        className="w-44 px-2 py-1 bg-white border border-gray-200 rounded text-xs focus:outline-none focus:border-blue-300"
                                        placeholder="版本描述（如：2025新年版）"
                                      />
                                      <button onClick={() => removeChannelVersion(ch, vi)}
                                        className="text-red-400 hover:text-red-600 text-xs">删除版本</button>
                                    </div>
                                    {[
                                      { key: 'ecommerce_main' as const, label: '电商主图' },
                                      { key: 'detail_module' as const, label: '详情页模块图' },
                                    ].map(ct => (
                                      <div key={ct.key} className="mb-2 last:mb-0">
                                        <div className="flex items-center justify-between mb-1">
                                          <span className="text-xs text-apple-text">{ct.label}</span>
                                          <div className="flex gap-1">
                                            <label className="text-xs text-blue-600 cursor-pointer hover:text-blue-700">
                                              <input type="file" multiple accept="image/*"
                                                onChange={(e) => handleChannelVersionUpload(ch, vi, ct.key, e)}
                                                className="hidden" />
                                              上传
                                            </label>
                                            <button onClick={() => addChannelVersionImageUrl(ch, vi, ct.key)}
                                              className="text-xs text-gray-500 hover:text-gray-700">+ URL</button>
                                          </div>
                                        </div>
                                        {getChannelVersionImages(ch, vi, ct.key).length > 0 && (
                                          <div className="grid grid-cols-4 gap-2">
                                            {getChannelVersionImages(ch, vi, ct.key).map((img, ii) => (
                                              <div key={ii} className="relative group">
                                                {(img.startsWith('http') || img.startsWith('/uploads')) ? (
                                                  <div className="aspect-square bg-gray-100 rounded-lg overflow-hidden cursor-pointer"
                                                    onClick={() => setLightboxImage(img.startsWith('/') ? `http://192.168.3.109:8000${img}` : img)}>
                                                    <img src={img.startsWith('/') ? `http://192.168.3.109:8000${img}` : img} alt="" className="w-full h-full object-cover" />
                                                  </div>
                                                ) : (
                                                  <input type="text" value={img}
                                                    onChange={(e) => updateChannelVersionImageUrl(ch, vi, ct.key, ii, e.target.value)}
                                                    className="w-full aspect-square px-2 py-1 bg-gray-100 border border-gray-200 rounded-lg text-xs" placeholder="URL" />
                                                )}
                                                <button onClick={() => removeChannelVersionImage(ch, vi, ct.key, ii)}
                                                  className="absolute top-1 right-1 w-5 h-5 bg-red-500 text-white rounded-full text-xs opacity-0 group-hover:opacity-100 flex items-center justify-center">✕</button>
                                              </div>
                                            ))}
                                          </div>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        )
                      })}
                      {allChannels.filter(ch => !activeChannels.includes(ch)).length > 0 && (
                        <div className="flex flex-wrap gap-2 pt-1">
                          <span className="text-xs text-apple-text self-center">添加渠道：</span>
                          {allChannels.filter(ch => !activeChannels.includes(ch)).map(ch => (
                            <button key={ch} onClick={() => setActiveChannels([...activeChannels, ch])}
                              className="px-3 py-1 text-xs bg-gray-100 text-gray-600 rounded-full hover:bg-blue-100 hover:text-blue-700 transition-colors">
                              + {ch}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  ) : (
                    ('fields' in section ? section.fields : []).map(f => {
                      const isVideo = f.key === 'social_video_urls'
                      const images = isVideo ? (media as any)[f.key] || [] : getMediaImages(f.key)
                      return (
                        <div key={f.key}>
                          <div className="flex items-center justify-between mb-1.5">
                            <span className="text-xs text-apple-text">{f.label}</span>
                            <div className="flex gap-1">
                              <label className="text-xs text-blue-600 cursor-pointer hover:text-blue-700">
                                <input type="file" multiple accept={isVideo ? 'video/*' : 'image/*'}
                                  onChange={(e) => handleMediaUpload(f.key, e)}
                                  className="hidden" />
                                上传
                              </label>
                              <button onClick={() => addMediaUrl(f.key)}
                                className="text-xs text-gray-500 hover:text-gray-700">+ URL</button>
                            </div>
                          </div>
                          {images.length > 0 && (
                            isVideo ? (
                              <div className="space-y-1.5">
                                {images.map((url: string, i: number) => (
                                  <div key={i} className="flex items-center gap-2">
                                    <input type="text" value={url}
                                      onChange={(e) => updateMediaUrl(f.key, i, e.target.value)}
                                      className="flex-1 px-2 py-1 bg-white border border-gray-200 rounded text-xs focus:outline-none focus:border-blue-300"
                                      placeholder="视频URL" />
                                    <button onClick={() => removeMediaUrl(f.key, i)}
                                      className="text-red-400 hover:text-red-600 text-xs">✕</button>
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <div className="grid grid-cols-4 gap-2">
                                {images.map((img: string, i: number) => (
                                  <div key={i} className="relative group">
                                    {(img.startsWith('http') || img.startsWith('/uploads')) ? (
                                      <div className="aspect-square bg-gray-100 rounded-lg overflow-hidden cursor-pointer"
                                        onClick={() => setLightboxImage(img.startsWith('/') ? `http://192.168.3.109:8000${img}` : img)}>
                                        <img src={img.startsWith('/') ? `http://192.168.3.109:8000${img}` : img} alt="" className="w-full h-full object-cover" />
                                      </div>
                                    ) : (
                                      <input type="text" value={img}
                                        onChange={(e) => updateMediaUrl(f.key, i, e.target.value)}
                                        className="w-full aspect-square px-2 py-1 bg-gray-100 border border-gray-200 rounded-lg text-xs" placeholder="URL" />
                                    )}
                                    <button onClick={() => removeMediaUrl(f.key, i)}
                                      className="absolute top-1 right-1 w-5 h-5 bg-red-500 text-white rounded-full text-xs opacity-0 group-hover:opacity-100 flex items-center justify-center">✕</button>
                                  </div>
                                ))}
                              </div>
                            )
                          )}
                        </div>
                      )
                    })
                  )}
                </div>
              )}
            </div>
          ))}
        </div>

        {lightboxImage && (
          <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50" onClick={() => setLightboxImage(null)}>
            <button onClick={() => setLightboxImage(null)} className="absolute top-4 right-4 text-white text-2xl hover:text-gray-300">✕</button>
            <img src={lightboxImage} alt="预览" className="max-w-full max-h-full object-contain" onClick={(e) => e.stopPropagation()} />
          </div>
        )}

        <div className="glass rounded-xl p-6">
          <h2 className="text-lg font-semibold text-apple-text mb-4">🎯 L7 - 内容生成层</h2>

          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-medium text-apple-text">提示词模板</span>
              <button onClick={() => addPromptTemplate()} className="text-sm text-blue-600 hover:text-blue-700">+ 添加模板</button>
            </div>
            <div className="space-y-3">
              {(prompt.prompts || []).map((p, i) => (
                <div key={i} className="bg-white/50 rounded-lg p-3">
                  <div className="flex items-center gap-3 mb-2">
                    <span className="text-xs font-bold text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded shrink-0">#{i + 1}</span>
                    <select value={p.prompt_type} onChange={(e) => updatePromptTemplate(i, 'prompt_type', e.target.value)}
                      className="w-24 bg-transparent border border-gray-100 rounded px-2 py-1 text-xs focus:outline-none focus:border-blue-300">
                      <option value="image">图像</option>
                      <option value="video">视频</option>
                    </select>
                    <input type="text" value={p.prompt_name}
                      onChange={(e) => updatePromptTemplate(i, 'prompt_name', e.target.value)}
                      className="flex-1 bg-transparent border border-gray-100 rounded px-2 py-1 text-sm focus:outline-none focus:border-blue-300"
                      placeholder="模板名称" />
                    <input type="text" value={p.version || ''}
                      onChange={(e) => updatePromptTemplate(i, 'version', e.target.value)}
                      className="w-16 bg-transparent border border-gray-100 rounded px-2 py-1 text-xs focus:outline-none focus:border-blue-300"
                      placeholder="版本" />
                    <button onClick={() => removePromptTemplate(i)}
                      className="text-red-400 hover:text-red-600 text-xs shrink-0">✕</button>
                  </div>
                  <textarea value={p.prompt_text}
                    onChange={(e) => updatePromptTemplate(i, 'prompt_text', e.target.value)}
                    className="w-full px-3 py-2 bg-white/60 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
                    rows={3} placeholder="提示词内容，支持 {变量} 占位符" />
                </div>
              ))}
              {(prompt.prompts || []).length === 0 && (
                <p className="text-xs text-apple-text">点击"+ 添加模板"创建提示词模板</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
