# Miremo Paper Studio

使用 Next.js 展示论文中的 TERM 候选、模型判断、定义和原文位置。

网页内置《Attention Is All You Need》的真实历史模型结果：998 条候选均有模型判断记录，最终保留 160 条术语。支持搜索、状态筛选、正文高亮、逐次位置跳转、Meta 和批注查看，以及 TERM 集合导出。

**网页是纯静态展示，不创建或执行处理任务，不需要 API Key、运行口令或数据库。** 导出在浏览器本地完成。

## 本地预览

Node.js 22.17+、pnpm 10。

```sh
pnpm install
pnpm dev
```

打开 [localhost:3030](http://localhost:3030)。左侧选择候选词，中间查看原文高亮，右侧查看模型判断和定义。全部候选均保留，包括排除和待确认的词。

## 部署到 Vercel

在 Vercel 导入本仓库，使用 Next.js 框架预设和默认安装设置，构建命令为 `pnpm build`。项目配置了 `output: 'export'`，构建后输出 `out/` 静态文件。无需配置环境变量，也不会调用模型服务。

本地检查生产构建：

```sh
pnpm build
pnpm start
```

`pnpm start` 在 3030 端口预览 `out/`。这些文件也可以部署到其他静态托管服务。

## 数据与输出

示例数据见 [data/attention.json](data/attention.json)，来源和处理说明见 [data/README.md](data/README.md)。网页使用构建时的数据快照，更新数据后重新构建即可更新展示。

导出的 TERM 集合包括：

- `terms`：保留的术语、规范名称、别名、定义、成员 ID 和证据。
- `candidates`：全部候选、算法分数、精确位置、阅读批注及模型判断。
- `documentMeta` / `chapterMeta`：阅读概述、关注方向和来源。
- `provenance`：模型、算法和结果来源。

字符位置采用 JavaScript UTF-16 索引，相对于对应的正文分片；高亮前会再次检查原文。没有精确词面位置的候选只提供证据段落跳转。模型处理结果尚待人工确认，不等于知识图谱采纳。

## 可选：命令行处理论文

仓库保留独立的 TypeScript 处理工具，供本地生成新结果；它不会在展示网站中运行。

复制 `.env.example` 为 `.env.local`，填写 `PAPER_API_KEY`、`PAPER_BASE_URL` 和 `PAPER_MODEL`。模型须支持 OpenAI-compatible Chat Completions 和 JSON object 输出。可通过 `PAPER_REQUEST_OPTIONS` 提供服务商的额外请求字段。

```sh
pnpm paper --attention
pnpm paper --input paper.md --title "My paper" --output terms.json
pnpm paper --resume RUN_ID
pnpm paper --export attention-demo --output attention-terms.json
```

流程为：术语预选 → 文章／章节 Meta → 逐片细读 → 候选判断与定义整理。任务保存在 `.paper-runs/`，失败步骤不会标为完成，已校验的模型响应可复用。`PAPER_MAX_CALLS` 限制每个任务累计请求次数，不是金额上限。修改模型配置应创建新任务。

新任务使用 winkNLP 英文词性处理与 TypeScript C-Value，抽取 1–5 词短语，不做 Top-K 截断；模型逐候选生成有原文依据的判断和定义，不跨候选 ID 自动归并。内置历史结果使用 spaCy + JATE，并经过后续归并和审阅，两者结果不保证相同。

仅处理 TERM，不需要输入 Ontology，不抽取关系或写入知识图谱。输入支持英文 Markdown / 文本和内置 Attention 提取文本，不提供 PDF 文件解析。

服务异常退出后，如任务提示“正在处理”，先确认对应进程已停止，再清理该任务目录中的 `active.lock` 并继续。

## 测试

```sh
pnpm test
pnpm typecheck
pnpm build
```

测试使用模拟模型响应，不产生模型 API 费用。

## 许可证

代码采用 [MIT](LICENSE)。论文与第三方依赖遵循各自的授权。

配套文章：[从文档到知识图谱：用 Ontology 引导文档预处理](https://www.imassen.com/blog/2026-10-28-doc-ontology-keywords-draft/)。
