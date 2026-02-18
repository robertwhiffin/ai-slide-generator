import { useState, useRef, useEffect } from "react"
import { Save, Download, Play } from "lucide-react"
import { Button } from "@/ui/button"
import { SidebarTrigger } from "@/ui/sidebar"
import { Separator } from "@/ui/separator"

interface PageHeaderProps {
  title: string
  subtitle?: string
  onSave?: () => void
  onExport?: () => void
  onPresent?: () => void
  onTitleChange?: (newTitle: string) => void
  profileSelector?: React.ReactNode
  isGenerating?: boolean
}

export function PageHeader({
  title,
  subtitle,
  onSave,
  onExport,
  onPresent,
  onTitleChange,
  profileSelector,
  isGenerating = false,
}: PageHeaderProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [editedTitle, setEditedTitle] = useState(title)
  const inputRef = useRef<HTMLInputElement>(null)

  // Update editedTitle when title prop changes
  useEffect(() => {
    setEditedTitle(title)
  }, [title])

  // Focus input when entering edit mode
  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [isEditing])

  const handleSave = () => {
    const trimmed = editedTitle.trim()
    if (trimmed && trimmed !== title && onTitleChange) {
      onTitleChange(trimmed)
    } else {
      setEditedTitle(title) // Reset if empty or unchanged
    }
    setIsEditing(false)
  }

  const handleCancel = () => {
    setEditedTitle(title)
    setIsEditing(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handleSave()
    } else if (e.key === 'Escape') {
      handleCancel()
    }
  }
  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-border bg-card px-4">
      {/* Sidebar Toggle */}
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="h-4" />

      {/* Left: Title */}
      <div className="flex flex-1 items-center">
        <div className="flex flex-col">
          {isEditing ? (
            <input
              ref={inputRef}
              type="text"
              value={editedTitle}
              onChange={(e) => setEditedTitle(e.target.value)}
              onBlur={handleSave}
              onKeyDown={handleKeyDown}
              className="text-sm font-medium text-foreground bg-background border border-border rounded px-2 py-0.5 focus:outline-none focus:ring-2 focus:ring-primary"
              disabled={isGenerating}
            />
          ) : (
            <button
              onClick={() => onTitleChange && setIsEditing(true)}
              className="text-sm font-medium text-foreground hover:text-primary transition-colors text-left"
              disabled={isGenerating || !onTitleChange}
            >
              {title}
            </button>
          )}
          {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
        </div>
      </div>

      {/* Right: Actions and Profile */}
      <div className="flex items-center gap-2">
        {onSave && (
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={onSave}
            disabled={isGenerating}
          >
            <Save className="size-3.5" />
            Save
          </Button>
        )}
        {onExport && (
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={onExport}
            disabled={isGenerating}
          >
            <Download className="size-3.5" />
            Export
          </Button>
        )}
        {onPresent && (
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={onPresent}
            disabled={isGenerating}
          >
            <Play className="size-3.5" />
            Present
          </Button>
        )}

        {profileSelector && (
          <>
            <div className="mx-2 h-5 w-px bg-border" />
            {profileSelector}
          </>
        )}
      </div>
    </header>
  )
}
