# Miremo Paper Studio

使用 Next.js 阅读论文、运行 TERM 抽取，并查看每个候选词的模型判断与原文位置。前后端均为 TypeScript，运行时无需 Python。

- **执行流水线**：术语预选 → 文章／章节 Meta → 逐片细读 → 候选判断与定义整理 → 导出 TERM ontology JSON。
- **阅读结果页面**：候选搜索和状态筛选、正文高亮、逐次出现位置跳转、规范名称、别名、定义、阅读批注及证据。

内置《Attention Is All You Need》的真实历史模型结果：998 条候选均有模型判断记录，最终保留 160 条术语。无需配置 API Key 即可查看。模型处理不等于人工确认或知识图谱采纳。

## 启动

Node.js 22.17+、pnpm 10。

```sh
pnpm install
pnpm dev
```

打开 [localhost:3030](http://localhost:3030)。左侧选择候选词，中间查看原文高亮，右侧查看模型判断和定义。所有候选都保留，包括被排除和待确认的词；可切换到“保留”筛选。

## 执行新任务

复制 `.env.example` 为 `.env.local`，设置：

```dotenv
PAPER_API_KEY=your-api-key
PAPER_BASE_URL=https://your-provider.example/v1
PAPER_MODEL=your-model
PAPER_RUN_TOKEN=your-private-access-passphrase
PAPER_MAX_CALLS=500
PAPER_REQUEST_OPTIONS={}
```

模型须支持 OpenAI-compatible Chat Completions 和 JSON object 输出。`PAPER_REQUEST_OPTIONS` 可填服务商所需的额外请求字段；不能覆盖模型、消息或输出格式。服务端保管 API Key；浏览器通过运行口令创建或继续任务。

重启开发服务，点击“新建处理任务”，选择 Attention 正文或粘贴英文 Markdown / 纯文本，输入运行口令后开始。执行期间保持页面打开；暂停会在当前步骤结束后生效。任务数据保存在 `.paper-runs/`，重新打开任务 URL 后输入口令可继续。

也可使用命令行（读取 `.env.local`）：

```sh
pnpm paper --attention
pnpm paper --input paper.md --title "My paper" --output terms.json
pnpm paper --resume RUN_ID
pnpm paper --export attention-demo --output attention-terms.json
```

`PAPER_MAX_CALLS` 是每个任务累计请求尝试数的上限，不是金额上限。失败步骤不会标为完成；经过校验的模型响应可复用。修改模型配置应创建新任务。

## 输出

导出的 TERM 集合包括：

- `terms`：保留的术语、规范名称、别名、定义、成员 ID 和证据。
- `candidates`：全部候选、算法分数、精确出现位置、阅读批注、模型处理状态及保留／排除／待确认判断。
- `documentMeta` / `chapterMeta`：阅读概述、关注方向和来源。
- `provenance`：模型、算法及结果来源。

字符位置采用 JavaScript UTF-16 索引，相对于对应的正文分片；高亮前会再次检查原文。没有精确词面位置的模型新发现项只提供证据段落跳转。`complete: false` 表示流水线尚未完成。所有结果的 `finalAdoption` 均为 `false`。

## 算法与范围

新任务使用 winkNLP 英文分词／词性标注和 TypeScript C-Value：抽取 1–5 词的形容词／名词短语，以名词结尾，按词形归一汇总全文频次，不做 Top-K 截断。模型按分片补充阅读批注、发现新术语，再逐候选生成有原文依据的判断和定义。新任务不跨候选 ID 自动归并；同名项保留独立记录以供复核。

内置历史结果使用 spaCy + JATE，并经过后续归并、去噪及追加审阅。它展示已有的真实模型运行结果，不代表使用当前 TypeScript 流水线重新运行；两者的候选数量不保证相同。详细数据说明见 [data/README.md](data/README.md)。

仅处理 TERM，不需要输入 Ontology，不抽取关系或写入知识图谱。输入支持英文 Markdown / 文本及内置 Attention 提取文本；PDF 图片、公式和表格请对照原论文，当前版本不提供 PDF 文件解析。

## 运行与测试

```sh
pnpm test
pnpm typecheck
pnpm build
pnpm start
```

默认采用持久化文件系统，适合本地或自托管 Node 服务。执行接口每次推进一个模型步骤，页面或 CLI 连续调用。请勿直接将文件存储运行模式部署到临时文件系统的 Serverless 环境；公开只读展示可使用内置示例，在线执行需要持久化存储和受保护的运行口令。

服务异常退出后，若任务提示“正在处理”，先确认对应进程已停止，再清理该任务目录下的 `active.lock` 并继续。不要在任务执行时移除锁。

## 许可证

代码采用 [MIT](LICENSE)。论文与第三方依赖遵循各自的授权。

配套文章：[从文档到知识图谱：用 Ontology 引导文档预处理](https://www.imassen.com/blog/2026-10-28-doc-ontology-keywords-draft/)。
