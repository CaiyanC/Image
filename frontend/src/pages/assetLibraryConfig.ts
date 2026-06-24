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
  { code: '05', name: '渠道销售图', icon: '🛒' },
  { code: '06', name: '视频素材', icon: '🎬' },
  { code: '07', name: 'AI 生成图', icon: '🤖' },
  { code: '08', name: '参考归档禁用图', icon: '📁' },
]

export const ASSET_SUB_CATEGORIES: AssetSubCategory[] = [
  { categoryCode: '01', name: '白底图', materialType: 'whiteBackground' },
  { categoryCode: '01', name: '多角度图', materialType: 'multiAngle' },
  { categoryCode: '01', name: '配件图', materialType: 'accessory' },
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
  { categoryCode: '03', name: '其他说明', materialType: 'otherDesc' },
  { categoryCode: '04', name: '硬核露营', materialType: 'hardcoreCamping' },
  { categoryCode: '04', name: '徒步', materialType: 'hiking' },
  { categoryCode: '04', name: '车露营', materialType: 'carCamping' },
  { categoryCode: '04', name: '家庭露营', materialType: 'familyCamping' },
  { categoryCode: '04', name: '雪地', materialType: 'snow' },
  { categoryCode: '04', name: '森林', materialType: 'forest' },
  { categoryCode: '04', name: '湖边', materialType: 'lakeside' },
  { categoryCode: '04', name: '室内', materialType: 'indoor' },
  { categoryCode: '05', name: 'Amazon', materialType: 'amazonMain' },
  { categoryCode: '05', name: '天猫', materialType: 'tmallMain' },
  { categoryCode: '05', name: '京东', materialType: 'jdMain' },
  { categoryCode: '05', name: '社媒宣发', materialType: 'socialMedia' },
  { categoryCode: '05', name: '活动广告', materialType: 'campaignAd' },
  { categoryCode: '05', name: 'eBay', materialType: 'ebay' },
  { categoryCode: '05', name: 'Temu', materialType: 'temu' },
  { categoryCode: '05', name: '独立站', materialType: 'standalone' },
  { categoryCode: '05', name: '阿里国际站', materialType: 'alibaba' },
  { categoryCode: '05', name: '速卖通', materialType: 'aliexpress' },
  { categoryCode: '05', name: '拼多多', materialType: 'pinduoduo' },
  { categoryCode: '05', name: '抖音', materialType: 'douyin' },
  { categoryCode: '05', name: '小红书', materialType: 'xiaohongshu' },
  { categoryCode: '05', name: '快手', materialType: 'kuaishou' },
  { categoryCode: '05', name: '得物', materialType: 'dewu' },
  { categoryCode: '06', name: '视频', materialType: 'video' },
  { categoryCode: '07', name: 'AI 场景图', materialType: 'aiScene' },
  { categoryCode: '07', name: 'AI 产品图', materialType: 'aiProduct' },
  { categoryCode: '07', name: 'AI 提示词模板', materialType: 'aiPrompt' },
  { categoryCode: '08', name: '竞品参考', materialType: 'competitor' },
  { categoryCode: '08', name: '历史版本', materialType: 'historical' },
  { categoryCode: '08', name: '旧包装', materialType: 'oldPack' },
  { categoryCode: '08', name: '禁用素材', materialType: 'banned' },
]

export const MULTI_ANGLE_SLOTS = [
  { key: 'front', label: '正面', accept: 'image/*' },
  { key: 'side', label: '侧面', accept: 'image/*' },
  { key: 'back', label: '背面', accept: 'image/*' },
  { key: 'detail', label: '特写', accept: 'image/*' },
]

export const AMAZON_SLOTS = [
  { key: 'mainImage', label: '主图', accept: 'image/*' },
  { key: 'aPlus', label: 'A+', accept: 'image/*' },
]

export const PLATFORM_DETAIL_SLOTS = [
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
  { key: 'product_tags', label: '产品', color: 'bg-amber-100 text-amber-700' },
  { key: 'material_type_tags', label: '类型', color: 'bg-blue-100 text-blue-700' },
  { key: 'usage_tags', label: '用途', color: 'bg-green-100 text-green-700' },
  { key: 'version_tags', label: '版本', color: 'bg-purple-100 text-purple-700' },
  { key: 'risk_tags', label: '风险', color: 'bg-red-100 text-red-700' },
  { key: 'channel_tags', label: '渠道', color: 'bg-teal-100 text-teal-700' },
  { key: 'language_tags', label: '语言', color: 'bg-stone-100 text-stone-700' },
] as const

export const TAG_PRESETS: Record<string, string[]> = {
  product_tags: ['酒精炉', '套锅', '分体炉', '水壶', '水袋', '登山杖', '炉具', '餐具', '咖啡器具', '帐篷', '睡袋', '灯具', '椅子', '桌子'],
  material_type_tags: ['白底图', '场景图', '结构图', '爆炸图', '尺寸图', '功能图', '参数图', '视频', '短视频'],
  usage_tags: ['AI 客服', '电商主图', '详情页', '社媒帖文', '广告素材', '产品页', 'A+', '说明书'],
  version_tags: ['当前版本', '历史版本', '量产版', 'V1', 'V2', 'V3', '样品版'],
  risk_tags: ['禁止对外', '仅内部参考', '待确认版权', '未授权', '过期版本'],
  channel_tags: ['Amazon', '天猫', '京东', 'eBay', 'Temu', '阿里国际站', '速卖通', '独立站', '抖音', '小红书', '拼多多', '快手', '得物'],
  language_tags: ['中文', '英文', '日文', '韩文', '德文', '法文', '西班牙文', '无文字'],
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
