# ShopMind 便捷命令（WSL / Git Bash 用；Windows 原生也可直接用 README 里的 uv run 命令）
.PHONY: up down doctor p1 p2-ingest p2-demo p2-eval p3 p5-build p5-compare

up:            ## 起 4 个中间件
	docker compose up -d
	uv run shopmind doctor

down:          ## 停中间件（保留数据）
	docker compose down

doctor:        ## 基础设施自检
	uv run shopmind doctor

p1:            ## P1 供血
	uv run shopmind p1 run

p2-ingest:     ## P2 知识入库
	uv run shopmind p2 ingest

p2-demo:       ## P2 端到端演示
	uv run shopmind p2 demo

p2-eval:       ## P2 三套评测
	uv run shopmind p2 eval

p3:            ## P3 直播切片
	uv run shopmind p3 run

p5-build:      ## P5 构建 SFT 语料
	uv run shopmind p5 build-dataset

p5-compare:    ## P5 before/after 对比
	uv run shopmind p5 compare
