export interface AssetCategory {
  code: string
  name: string
  icon: string
}

export interface AssetSubCategory {
  categoryCode: string
  name: string
  materialType: string
}

export const ASSET_CATEGORIES: AssetCategory[] = [
  { code: '01', name: '产品标准图', icon: '📷' },
  { code: '02', name: '产品信息图', icon: '📐' },
  { code: '03', name: '使用说明图', icon: '📖' },
  { code: '04', name: '场景内容图', icon: '🏕️' },
  { code: '05', name: '电商与品牌图', icon: '🛒' },
  { code: '06', name: '视频素材', icon: '🎬' },
  { code: '08', name: '历史与禁用归档', icon: '📁' },
]

export const ASSET_SUB_CATEGORIES: AssetSubCategory[] = [
  { categoryCode: '02', name: '3D图', materialType: 'threeD' },
  { categoryCode: '02', name: '功能特写', materialType: 'functionCloseup' },
  { categoryCode: '04', name: '汽车露营', materialType: 'carCampingActivity' },
  { categoryCode: '04', name: '骑行', materialType: 'cycling' },
  { categoryCode: '04', name: '摩旅', materialType: 'motorcycling' },
  { categoryCode: '04', name: '狩猎', materialType: 'hunting' },
  { categoryCode: '04', name: '垂钓', materialType: 'fishing' },
  { categoryCode: '06', name: '开箱视频', materialType: 'unboxingVideo' },
  { categoryCode: '06', name: '操作视频', materialType: 'operationVideo' },
  { categoryCode: '06', name: '测试视频', materialType: 'testingVideo' },
  { categoryCode: '06', name: '使用场景视频', materialType: 'usageSceneVideo' },
  { categoryCode: '06', name: '国内达人视频', materialType: 'domesticCreatorVideo' },
  { categoryCode: '06', name: '跨境达人视频', materialType: 'crossBorderCreatorVideo' },
  { categoryCode: '01', name: '白底图', materialType: 'whiteBackground' },
  { categoryCode: '01', name: '主体图', materialType: 'productBody' },
  { categoryCode: '01', name: '多角度图', materialType: 'multiAngle' },
  { categoryCode: '01', name: '配件图', materialType: 'accessory' },
  { categoryCode: '01', name: '收纳袋图', materialType: 'storageBag' },
  { categoryCode: '01', name: '套装图', materialType: 'set' },
  { categoryCode: '01', name: '收纳前后图', materialType: 'packed' },
  { categoryCode: '02', name: '尺寸图', materialType: 'size' },
  { categoryCode: '02', name: '结构图', materialType: 'structure' },
  { categoryCode: '02', name: '爆炸图', materialType: 'exploded' },
  { categoryCode: '02', name: '功能示意图', materialType: 'functional' },
  { categoryCode: '02', name: '参数图', materialType: 'parameter' },
  { categoryCode: '02', name: '其他说明', materialType: 'otherDesc' },
  { categoryCode: '03', name: '安装步骤', materialType: 'install' },
  { categoryCode: '03', name: '点火步骤', materialType: 'ignite' },
  { categoryCode: '03', name: '清洁步骤', materialType: 'clean' },
  { categoryCode: '03', name: '安全说明', materialType: 'safety' },
  { categoryCode: '03', name: '售后易错图', materialType: 'afterSales' },
  { categoryCode: '03', name: '中文说明', materialType: 'manualZh' },
  { categoryCode: '03', name: '英文说明', materialType: 'manualEn' },
  { categoryCode: '03', name: '其他说明', materialType: 'otherDesc' },
  { categoryCode: '04', name: '硬核露营', materialType: 'hardcoreCamping' },
  { categoryCode: '04', name: '徒步', materialType: 'hiking' },
  { categoryCode: '04', name: '车露营', materialType: 'carCamping' },
  { categoryCode: '04', name: '家庭露营', materialType: 'familyCamping' },
  { categoryCode: '04', name: '雪地', materialType: 'snow' },
  { categoryCode: '04', name: '森林', materialType: 'forest' },
  { categoryCode: '04', name: '湖边', materialType: 'lakeside' },
  { categoryCode: '04', name: '室内', materialType: 'indoor' },
  { categoryCode: '05', name: '国内电商', materialType: 'domesticEcommerce' },
  { categoryCode: '05', name: '跨境电商', materialType: 'crossBorderEcommerce' },
  { categoryCode: '05', name: '国内品牌', materialType: 'domesticBrand' },
  { categoryCode: '05', name: '跨境品牌', materialType: 'crossBorderBrand' },
  { categoryCode: '06', name: '白底视频', materialType: 'whiteBackgroundVideo' },
  { categoryCode: '06', name: '场景短视频（≤30秒）', materialType: 'sceneShortVideo' },
  { categoryCode: '06', name: '场景长视频（>30秒）', materialType: 'sceneLongVideo' },
  { categoryCode: '08', name: '历史版本', materialType: 'historical' },
  { categoryCode: '08', name: '旧包装', materialType: 'oldPack' },
  { categoryCode: '08', name: '禁用素材', materialType: 'banned' },
]

export function getCategoryTagValue(categoryCode: string, subCategory?: string | null) {
  return subCategory ? `${categoryCode}/${subCategory}` : ''
}

export function getCategoryTagLabel(value: string) {
  const [categoryCode, ...subParts] = value.split('/')
  const subCategory = subParts.join('/')
  if (!categoryCode || !subCategory) return value
  return `${getCategoryName(categoryCode)} / ${subCategory}`
}

export const CATEGORY_TAG_PRESETS = ASSET_SUB_CATEGORIES.map(item => getCategoryTagValue(item.categoryCode, item.name))

export const MULTI_ANGLE_SLOTS = [
  { key: 'front', label: '正面', accept: 'image/*' },
  { key: 'side', label: '侧面', accept: 'image/*' },
  { key: 'back', label: '背面', accept: 'image/*' },
  { key: 'detail', label: '特写', accept: 'image/*' },
]

export const CROSS_BORDER_ECOMMERCE_SLOTS = [
  { key: 'mainImage', label: '主图', accept: 'image/*' },
  { key: 'aPlus', label: 'A+', accept: 'image/*' },
]

export const DOMESTIC_ECOMMERCE_SLOTS = [
  { key: 'mainImage', label: '主图', accept: 'image/*' },
  { key: 'detailPage', label: '详情页', accept: 'image/*' },
]

export const STATUS_TO_EN: Record<string, string> = {
  待审核: 'pending',
  审核中: 'reviewing',
  已通过: 'approved',
  需修改: 'needsrevision',
  禁用: 'banned',
  归档历史版本: 'archived',
}

export const STATUS_OPTIONS = Object.keys(STATUS_TO_EN)

export const TAG_DIMENSIONS = [
  { key: 'category_tags', label: '归属分类（可多选）', color: 'bg-teal-100 text-teal-700' },
  { key: 'quality_check_tags', label: '标准检查（未标注即未检查）', color: 'bg-violet-100 text-violet-700' },
  { key: 'material_type_tags', label: '素材形式（可多选）', color: 'bg-blue-100 text-blue-700' },
  { key: 'subject_tags', label: '拍摄对象', color: 'bg-cyan-100 text-cyan-700' },
  { key: 'composition_tags', label: '人物构成', color: 'bg-lime-100 text-lime-700' },
  { key: 'view_tags', label: '多角度子标签 / 拍摄视角', color: 'bg-sky-100 text-sky-700' },
  { key: 'expression_tags', label: '表达', color: 'bg-indigo-100 text-indigo-700' },
  { key: 'selling_point_tags', label: '卖点', color: 'bg-orange-100 text-orange-700' },
  { key: 'scene_tags', label: '场景', color: 'bg-emerald-100 text-emerald-700' },
  { key: 'mood_tags', label: '氛围', color: 'bg-pink-100 text-pink-700' },
  { key: 'product_tags', label: '产品', color: 'bg-amber-100 text-amber-700' },
  { key: 'usage_tags', label: '用途', color: 'bg-green-100 text-green-700' },
  { key: 'version_tags', label: '版本', color: 'bg-purple-100 text-purple-700' },
  { key: 'risk_tags', label: '风险', color: 'bg-red-100 text-red-700' },
  { key: 'channel_tags', label: '渠道', color: 'bg-teal-100 text-teal-700' },
  { key: 'language_tags', label: '语言', color: 'bg-stone-100 text-stone-700' },
] as const

export const TAG_PRESETS: Record<string, string[]> = {
  category_tags: CATEGORY_TAG_PRESETS,
  quality_check_tags: ['完整性通过', '完整性需修改', '瑕疵检查通过', '瑕疵检查需修改', '质感通过', '质感需修改', '复用性通过', '复用性需修改'],
  material_type_tags: ['白底图', '主体图', '配件图', '多角度图', '收纳袋图', '套装图', '收纳前后图', '场景内容图', '结构图', '爆炸图', '尺寸图', '功能示意图', '参数图', '白底视频', '场景短视频（≤30秒）', '场景长视频（>30秒）', '场景短视频', '场景长视频'],
  subject_tags: ['主体', '配件', '收纳袋', '套装'],
  composition_tags: ['带人物', '纯产品'],
  view_tags: ['正视', '侧视', '背视', '特写'],
  expression_tags: ['卖点图', '场景图', '人物场景图', '纯产品场景图', '氛围图'],
  selling_point_tags: ['轻量便携', '易收纳', '耐用', '导热均匀', '保温', '易清洁', '安全', '容量大'],
  scene_tags: ['徒步', '汽车露营', '骑行', '摩旅', '狩猎', '垂钓', '硬核露营', '车露', '家庭露营', '雪地', '森林', '湖边', '室内'],
  mood_tags: ['硬核', '温暖', '自由', '专业', '精致', '极简'],
  product_tags: ['酒精炉', '套锅', '分体炉', '水壶', '水袋', '登山杖', '炉具', '餐具', '咖啡器具', '帐篷', '睡袋', '灯具', '椅子', '桌子'],
  usage_tags: ['AI 客服', '电商主图', '详情页', '社媒帖文', '广告素材', '产品页', 'A+', '说明书'],
  version_tags: ['当前版本', '历史版本', '量产版', 'V1', 'V2', 'V3', '样品版'],
  risk_tags: ['禁止对外', '仅内部参考', '待确认版权', '未授权', '过期版本'],
  channel_tags: ['Amazon', '天猫', '京东', 'eBay', 'Temu', '阿里国际站', '速卖通', '独立站', '抖音', '小红书', '拼多多', '快手', '得物'],
  language_tags: ['中文', '英文', '日文', '韩文', '德文', '法文', '西班牙文', '无文字'],
}

export const ASSET_UPLOAD_LIMITS = {
  image: { maxBytes: 20 * 1024 * 1024, maxFiles: 20 },
  video: { maxBytes: 200 * 1024 * 1024, maxFiles: 5 },
} as const

export const ASSET_FIELD_GUIDE = [
  { name: '关联SKU与产品类型', definition: '主SKU用于文件管理；关联SKU让同一条素材出现在多个产品库中，无需重复上传。产品类型标签只描述酒精炉、套锅等类型，不代替SKU关联。' },
  { name: '说明与客服资料', definition: '使用说明分类支持PDF、Word（DOCX）附件与图片。PDF可受控预览，Word通过受控下载查阅；加密或含自动执行内容的附件不接受。' },
  { name: '主归档位置', definition: '先在页面上选择一个一级分类和一个二级分类，作为文件的主归档位置；它不是图片唯一身份。' },
  { name: '其他归属分类', definition: '同一张图片只上传一次，可以再勾选多个其他分类，例如“电商与品牌图 / 国内电商”；分类入口和筛选都会找到同一条素材。' },
  { name: '素材形式标签', definition: '可同时选择白底图、配件图、多角度图等多个标签。一张图可以同时属于多个形式，筛选时会分别出现。' },
  { name: '拍摄对象', definition: '主体、配件、收纳袋、套装，可多选；说明画面拍了什么，不替代白底或多角度形式。' },
  { name: '人物构成', definition: '带人物或纯产品二选一；未标注表示未知，不由系统猜测。场景环境仍需独立填写。' },
  { name: '多角度子标签', definition: '多角度图下面再选正面、侧面、背面或特写；一张具体图片只选一个视角，不能把正面和侧面混在同一张图上。' },
  { name: '场景环境', definition: '露营、徒步、雪地、森林等使用环境；与是否带人物、拍摄视角分别记录。旧角度/场景字段仅作为历史备注。' },
  { name: '市场、版位与渠道', definition: '国内/跨境电商和品牌是业务分组；主图、详情页、A+ 是版位；Amazon、天猫等才是具体渠道。上传时可多选适用渠道，第一个同时作为兼容旧素材的主渠道；主图/详情页/A+ 在上传槽位记录，也可通过用途标签标注。' },
  { name: '说明语言', definition: '中文说明对应 CN/中文，英文说明对应 EN/英文；它不代表国内或跨境市场，冲突需要修正。' },
  { name: '维护人与上传人', definition: '维护人负责收集与更新，可在上传前填写；上传操作人由登录账号自动记录，两者不必是同一个人。' },
  { name: '标准检查、审核与使用范围', definition: '完整性、瑕疵、质感、复用性分别记录通过或需修改，缺少记录表示未检查。审核、使用授权、公开和三类 AI 使用范围相互独立；只有全部资格满足时开关才生效，未知授权不能放行。' },
  { name: '视频分类 时长与容量', definition: '优先按开箱、操作、测试、使用场景、国内达人、跨境达人等内容分类。时长独立自动解析；旧短视频不超过30秒、长视频超过30秒的规则仅用于兼容历史分类。容量显示为已用量，不是已确认配额。' },
] as const

export function getUploadGuidelines(categoryCode: string, subCategory?: string | null) {
  const shared = [
    '上传后先进入待审核；视觉负责人和产品经理需核对可复用性、瑕疵与产品质感。',
    '系统会记录原文件名、尺寸、文件大小和上传操作，便于后续追溯。',
  ]
  if (categoryCode === '01') {
    return [
      '主体、配件、收纳袋和套装请放入对应分类；封面优先使用正视图。',
      '产品保持居中，主体在画面中的建议占比为 50%–60%，避免过小、裁切或明显瑕疵。',
      ...shared,
    ]
  }
  if (categoryCode === '04') {
    return [
      '场景内容图按环境归类，并在“人物构成”中区分“带人物”或“纯产品”；日景/夜景目前只作为待确认信息，不强制猜测或填入。',
      '不要把人物构成和场景环境混为同一标签；环境、人物构成和视角分别记录。',
      ...shared,
    ]
  }
  if (categoryCode === '05') {
    return [
      '先区分国内/跨境与电商/品牌，再用渠道标签标注 Amazon、天猫、京东等具体平台。',
      ...shared,
    ]
  }
  if (categoryCode === '06') {
    return [
      subCategory?.includes('短视频')
        ? '短视频时长应不超过 30 秒。'
        : subCategory?.includes('长视频')
          ? '长视频时长应超过 30 秒。'
          : '请先选择白底视频、场景短视频或场景长视频。',
      ...shared,
    ]
  }
  if (categoryCode === '08') {
    return [
      '这里只保存本 SKU 的历史版本、旧包装和禁用素材；竞品参考请勿挂在单个 SKU 下。',
      ...shared,
    ]
  }
  return shared
}

export const TAG_DISPLAY_LABELS: Record<string, string> = {
  正视: '正面',
  侧视: '侧面',
  背视: '背面',
}

export function getTagDisplayName(tag: string) {
  return TAG_DISPLAY_LABELS[tag] || (tag.includes('/') ? getCategoryTagLabel(tag) : tag)
}

export const ASSET_FILTER_DIMENSION_KEYS = [
  'category_tags',
  'quality_check_tags',
  'material_type_tags',
  'product_tags',
  'usage_tags',
  'version_tags',
  'risk_tags',
  'channel_tags',
  'language_tags',
  'view_tags',
  'subject_tags',
  'composition_tags',
  'expression_tags',
  'scene_tags',
  'selling_point_tags',
  'mood_tags',
] as const

export function getMaterialTypeDisplayName(materialType?: string | null) {
  if (!materialType) return '未标注'
  const subCategory = ASSET_SUB_CATEGORIES.find(item => item.materialType === materialType)
  if (subCategory) return subCategory.name
  const legacyLabels: Record<string, string> = {
    front: '正面',
    side: '侧面',
    back: '背面',
    detail: '特写',
    mainImage: '主图',
    detailPage: '详情页',
    aPlus: 'A+',
    video: '视频',
  }
  return legacyLabels[materialType] || materialType
}

export function getCategoryName(code: string) {
  return ASSET_CATEGORIES.find(category => category.code === code)?.name || code
}

export function getSubCategories(categoryCode: string) {
  return ASSET_SUB_CATEGORIES.filter(item => item.categoryCode === categoryCode)
}

export function getMaterialType(categoryCode: string, subCategory?: string | null) {
  return ASSET_SUB_CATEGORIES.find(
    item => item.categoryCode === categoryCode && item.name === subCategory,
  )?.materialType || null
}
