import { useState, useRef, useEffect } from "react"
import { Save, Download, Play, Share2, ChevronDown, FileDown, FileText, Presentation } from "lucide-react"
import { Button } from "@/ui/button"
import { SidebarTrigger } from "@/ui/sidebar"
import { Separator } from "@/ui/separator"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu"

interface PageHeaderProps {
  title: string
  subtitle?: string
  onSave?: () => void
  onShare?: () => void
  /** Single export action (legacy); ignored if export menu items are provided */
  onExport?: () => void
  onExportPPTX?: () => void
  onExportPDF?: () => void
  onExportGoogleSlides?: () => void
  onPresent?: () => void
  onTitleChange?: (newTitle: string) => void
  savePointDropdown?: React.ReactNode
  profileSelector?: React.ReactNode
  /** Shown next to Export button (e.g. "Capturing charts...", "Exporting to Google Slides…") */
  exportStatus?: string | null
  isGenerating?: boolean
  /** When true, only show Share (copy view link); hide Save, Export, Present */
  viewOnly?: boolean
}

export function PageHeader({
  title,
  subtitle,
  onSave,
  onShare,
  onExport,
  onExportPPTX,
  onExportPDF,
  onExportGoogleSlides,
  onPresent,
  onTitleChange,
  savePointDropdown,
  profileSelector,
  exportStatus,
  isGenerating = false,
  viewOnly = false,
}: PageHeaderProps) {
  const hasExportMenu = !viewOnly && (onExportPPTX ?? onExportPDF ?? onExportGoogleSlides)
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

      {/* Left: Title row (title + Save + version) and subtitle below */}
      <div className="flex min-w-0 flex-1 flex-col gap-0">
        <div className="flex items-center gap-2 min-w-0 leading-tight">
          {isEditing ? (
            <input
              ref={inputRef}
              type="text"
              value={editedTitle}
              onChange={(e) => setEditedTitle(e.target.value)}
              onBlur={handleSave}
              onKeyDown={handleKeyDown}
              className="min-w-0 max-w-xl py-0.5 text-sm font-medium text-foreground bg-background border border-border rounded px-2 focus:outline-none focus:ring-2 focus:ring-primary"
              disabled={isGenerating}
            />
          ) : (
            <button
              onClick={() => onTitleChange && setIsEditing(true)}
              className="min-w-0 max-w-xl truncate py-0.5 text-left text-sm font-medium leading-tight text-foreground hover:text-primary transition-colors"
              disabled={isGenerating || !onTitleChange || viewOnly}
            >
              {title}
            </button>
          )}
          {!viewOnly && onSave && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 shrink-0"
              onClick={onSave}
              disabled={isGenerating}
              title="Save session name"
            >
              <Save className="size-3.5" />
            </Button>
          )}
          {!viewOnly && savePointDropdown && (
            <div className="shrink-0 leading-tight">{savePointDropdown}</div>
          )}
        </div>
        {subtitle && <p className="mt-px text-xs leading-none text-muted-foreground truncate">{subtitle}</p>}
      </div>

      {/* Right: Export status, Export, Share, Present, Profile */}
      <div className="flex items-center gap-2">
        {exportStatus && (
          <span className="text-xs text-muted-foreground whitespace-nowrap max-w-[140px] truncate" title={exportStatus}>
            {exportStatus}
          </span>
        )}
        {!viewOnly && (hasExportMenu || onExport) && (
          hasExportMenu ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-1.5"
                  disabled={isGenerating}
                >
                  <Download className="size-3.5" />
                  Export
                  <ChevronDown className="size-3.5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {onExportPPTX && (
                  <DropdownMenuItem onClick={onExportPPTX} disabled={isGenerating}>
                    <FileDown className="size-3.5 mr-2" />
                    Download PPTX
                  </DropdownMenuItem>
                )}
                {onExportPDF && (
                  <DropdownMenuItem onClick={onExportPDF} disabled={isGenerating}>
                    <FileText className="size-3.5 mr-2" />
                    Download PDF
                  </DropdownMenuItem>
                )}
                {onExportGoogleSlides && (
                  <DropdownMenuItem onClick={onExportGoogleSlides} disabled={isGenerating}>
                    <Presentation className="size-3.5 mr-2" />
                    Export to Google Slides
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
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
          )
        )}
        {onShare && (
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={onShare}
            disabled={isGenerating}
          >
            <Share2 className="size-3.5" />
            Share
          </Button>
        )}
        {!viewOnly && onPresent && (
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
