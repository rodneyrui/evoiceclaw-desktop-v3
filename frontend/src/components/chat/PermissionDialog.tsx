/**
 * 权限请求对话框
 *
 * 替代阻塞式 window.confirm，用 React 渲染非阻塞对话框。
 * 当 Agent 需要提升安全级别执行 Shell 命令时显示。
 */

import type { PermissionRequestInfo } from "@/features/chat/useDirectChat";

interface PermissionDialogProps {
  permissionRequest: PermissionRequestInfo | null;
  onRespond: (approved: boolean) => void;
}

export function PermissionDialog({ permissionRequest, onRespond }: PermissionDialogProps) {
  if (!permissionRequest) return null;

  const { cmdName, command, currentLevel, requiredLevel } = permissionRequest;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-card border border-border rounded-2xl p-6 max-w-md w-full mx-4 shadow-2xl">
        {/* 标题 */}
        <div className="flex items-center gap-3 mb-4">
          <div className="w-9 h-9 rounded-full bg-amber-500/15 flex items-center justify-center shrink-0">
            <svg
              className="w-5 h-5 text-amber-500"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"
              />
            </svg>
          </div>
          <div>
            <h3 className="font-semibold text-foreground text-sm">权限请求</h3>
            <p className="text-xs text-muted-foreground">
              Agent 需要提升安全级别
            </p>
          </div>
        </div>

        {/* 命令信息 */}
        <div className="space-y-3 mb-5">
          <div className="bg-muted/50 rounded-lg p-3 space-y-2 text-xs">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">命令类型</span>
              <span className="font-mono font-medium text-foreground">{cmdName}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">级别变更</span>
              <span className="font-medium">
                <span className="text-muted-foreground">{currentLevel}</span>
                <span className="mx-1.5 text-muted-foreground/50">→</span>
                <span className="text-amber-500">{requiredLevel}</span>
              </span>
            </div>
          </div>

          {command && (
            <div className="bg-muted/30 rounded-lg p-3">
              <p className="text-[10px] text-muted-foreground mb-1.5">执行命令</p>
              <pre className="text-xs font-mono text-foreground whitespace-pre-wrap break-all max-h-28 overflow-y-auto leading-relaxed">
                {command}
              </pre>
            </div>
          )}
        </div>

        {/* 操作按钮 */}
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => onRespond(false)}
            className="flex-1 px-4 py-2.5 rounded-xl text-sm font-medium border border-border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
          >
            拒绝
          </button>
          <button
            type="button"
            onClick={() => onRespond(true)}
            className="flex-1 px-4 py-2.5 rounded-xl text-sm font-medium bg-amber-500 text-white hover:bg-amber-500/90 transition-colors"
          >
            批准
          </button>
        </div>
      </div>
    </div>
  );
}
