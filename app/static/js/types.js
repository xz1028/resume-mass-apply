/**
 * 类型契约（JSDoc）：与后端 Pydantic 响应模型字段名逐字一致（蛇形命名原样保留）。
 * 解析一律解构取用契约字段，后端新增可选字段被天然忽略不报错（spec 4.5.3）。
 * 本文件为纯类型注解，无运行时代码。
 */

/**
 * @typedef {Object} ResumeProfile 简历档案
 * @property {string} resume_id
 * @property {string} name
 * @property {string} format - pdf | doc | docx
 * @property {number} size_bytes
 * @property {boolean} is_default
 * @property {string} created_at - ISO 时间
 */

/**
 * @typedef {Object} ContactInfo 联系方式
 * @property {string|null} phone
 * @property {string|null} email
 */

/**
 * @typedef {Object} JobIntention 求职意向
 * @property {string|null} city
 * @property {number|null} salary_min
 * @property {number|null} salary_max
 * @property {string|null} industry
 */

/**
 * @typedef {Object} SeekerProfile 求职者档案
 * @property {string} user_id
 * @property {ContactInfo} contact
 * @property {JobIntention} intention
 */

/**
 * @typedef {Object} Position 职位
 * @property {string} position_id
 * @property {string} platform_id
 * @property {string} title
 * @property {string} company
 * @property {string} city
 * @property {number|null} salary_min
 * @property {number|null} salary_max
 * @property {string} industry
 * @property {string} experience_req
 * @property {string} publish_expire_at
 * @property {string} fetched_at
 */

/**
 * @typedef {Object} RecommendedPosition 推荐职位（Position 同结构 + 匹配度）
 * @property {string} position_id
 * @property {string} platform_id
 * @property {string} title
 * @property {string} company
 * @property {string} city
 * @property {number|null} salary_min
 * @property {number|null} salary_max
 * @property {string} industry
 * @property {string} experience_req
 * @property {string} publish_expire_at
 * @property {string} fetched_at
 * @property {number|null} match_score - 匹配度 0-100；降级时为 null
 */

/**
 * @typedef {Object} PositionPage 职位分页
 * @property {Array<Position>} items
 * @property {number} total
 * @property {number} page
 * @property {number} page_size
 * @property {Array<string>} not_updated_platforms
 * @property {string|null} suggestion
 */

/**
 * @typedef {Object} RecommendationResponse 推荐响应
 * @property {boolean} matching_unavailable
 * @property {string|null} message
 * @property {Array<RecommendedPosition>} items
 */

/**
 * @typedef {Object} RejectedItem 拦截明细
 * @property {string} position_id
 * @property {string} title
 * @property {string} reason
 */

/**
 * @typedef {Object} Checklist 投递清单
 * @property {number} position_count
 * @property {Object<string, number>} platform_distribution
 * @property {string} resume_name
 * @property {Array<RejectedItem>} rejected
 */

/**
 * @typedef {Object} DeliveryTask 投递任务
 * @property {string} task_id
 * @property {string} status - pending_confirm | executing | completed | cancelled
 * @property {string} created_at
 * @property {string} resume_name
 * @property {number} position_count
 * @property {number} success_count
 * @property {number} failed_count
 * @property {number} skipped_count
 */

/**
 * @typedef {Object} CreateTaskResponse 创建任务响应
 * @property {DeliveryTask} task
 * @property {Checklist} checklist
 */

/**
 * @typedef {Object} CancelResponse 取消任务响应
 * @property {string} task_id
 * @property {string} status - cancelled | cancelling
 * @property {number} delivered
 * @property {number} remaining
 */

/**
 * @typedef {Object} ResumeSnapshot 简历快照
 * @property {string} name
 * @property {string} format
 * @property {string} content_hash
 * @property {string} created_at
 */

/**
 * @typedef {Object} DeliveryRecord 投递记录
 * @property {string} record_id
 * @property {string} task_id
 * @property {string} position_id
 * @property {string} platform_id
 * @property {string} position_title
 * @property {string} company
 * @property {string} status - pending | delivered | viewed | interview_invited | rejected | failed | expired
 * @property {string|null} delivered_at
 * @property {string} status_updated_at
 * @property {string|null} failure_reason
 * @property {ResumeSnapshot} resume_snapshot
 */

/**
 * @typedef {Object} RecordPage 记录分页
 * @property {Array<DeliveryRecord>} items
 * @property {number} total
 * @property {number} page
 * @property {number} page_size
 */

/**
 * @typedef {Object} TrendPoint 趋势点
 * @property {string} date
 * @property {number} count
 */

/**
 * @typedef {Object} Statistics 投递统计
 * @property {number} total
 * @property {Object<string, number>} status_distribution
 * @property {Object<string, number>} platform_distribution
 * @property {Array<TrendPoint>} recent_7_days
 */

/**
 * @typedef {Object} Platform 平台
 * @property {string} platform_id
 * @property {string} name
 * @property {string} auth_status - authorized | expired | unauthorized
 * @property {boolean} degraded
 */

/**
 * @typedef {Object} BlacklistEntry 黑名单条目
 * @property {string} entry_id
 * @property {string} type - company | keyword
 * @property {string} content
 */

/**
 * ApiError：统一错误对象（api.js 中实现运行时类）
 * @typedef {Object} ApiError
 * @property {number} code - 业务错误码；0 表示网络层错误（不可达/超时）
 * @property {string} message
 * @property {number|null} httpStatus
 */

/**
 * ViewState：视图状态四相（每个独立数据区域一个实例，支撑分区降级）
 * @typedef {Object} ViewState
 * @property {'loading'|'ready'|'empty'|'error'} phase
 * @property {Object|null} data
 * @property {ApiError|null} error
 */

/**
 * 任务筛选条件（条件圈选）
 * @typedef {Object} FilterCondition
 * @property {string|null} [city]
 * @property {number|null} [salary_min]
 * @property {number|null} [salary_max]
 * @property {string|null} [industry]
 * @property {string|null} [keyword]
 * @property {string|null} [experience]
 * @property {number|null} [min_match_score]
 */