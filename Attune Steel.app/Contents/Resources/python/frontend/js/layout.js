/**
 * Voice Garden — Drag-and-drop dashboard layout customization
 */

class LayoutManager {
    constructor() {
        this.editMode = false;
        this.cards = [];
        this._boundDragStart = this._onDragStart.bind(this);
        this._boundDragOver = this._onDragOver.bind(this);
        this._boundDrop = this._onDrop.bind(this);
        this._boundDragEnd = this._onDragEnd.bind(this);
    }

    async init() {
        try {
            const data = await API.getLayout();
            if (data.layout && data.layout.length > 0) {
                this.applyLayout(data.layout);
            }
        } catch (e) {
            // No saved layout — use default order
        }
    }

    toggleEditMode() {
        this.editMode = !this.editMode;
        const container = document.getElementById('today-view');
        if (!container) return;

        const editBtn = document.getElementById('layout-edit-btn');

        if (this.editMode) {
            container.classList.add('layout-editing');
            if (editBtn) editBtn.classList.add('active');

            // Make dashboard cards draggable
            const cards = container.querySelectorAll('.dashboard-card');
            cards.forEach(card => {
                card.setAttribute('draggable', 'true');
                card.addEventListener('dragstart', this._boundDragStart);
                card.addEventListener('dragover', this._boundDragOver);
                card.addEventListener('drop', this._boundDrop);
                card.addEventListener('dragend', this._boundDragEnd);
            });
        } else {
            container.classList.remove('layout-editing');
            if (editBtn) editBtn.classList.remove('active');

            // Remove draggable and event listeners
            const cards = container.querySelectorAll('.dashboard-card');
            cards.forEach(card => {
                card.removeAttribute('draggable');
                card.removeEventListener('dragstart', this._boundDragStart);
                card.removeEventListener('dragover', this._boundDragOver);
                card.removeEventListener('drop', this._boundDrop);
                card.removeEventListener('dragend', this._boundDragEnd);
            });

            // Save layout
            this._saveLayout();
        }
    }

    _onDragStart(e) {
        e.target.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', e.target.dataset.cardId);
    }

    _onDragOver(e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        const card = e.target.closest('.dashboard-card');
        if (card && !card.classList.contains('dragging')) {
            card.classList.add('drag-over');
        }
    }

    _onDrop(e) {
        e.preventDefault();
        const draggedId = e.dataTransfer.getData('text/plain');
        const targetCard = e.target.closest('.dashboard-card');
        if (!targetCard) return;

        const container = document.getElementById('today-view');
        const draggedEl = container.querySelector(`[data-card-id="${draggedId}"]`);
        if (!draggedEl || draggedEl === targetCard) return;

        // Swap positions
        const parent = targetCard.parentNode;
        const targetNext = targetCard.nextSibling;
        if (targetNext === draggedEl) {
            parent.insertBefore(draggedEl, targetCard);
        } else {
            parent.insertBefore(draggedEl, targetCard);
        }

        // Clean up
        container.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
    }

    _onDragEnd(e) {
        e.target.classList.remove('dragging');
        document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
    }

    async _saveLayout() {
        const container = document.getElementById('today-view');
        const cards = container.querySelectorAll('.dashboard-card');
        const layout = [];
        cards.forEach((card, index) => {
            layout.push({
                card_id: card.dataset.cardId,
                sort_order: index,
                visible: card.style.display !== 'none' ? 1 : 0
            });
        });

        try {
            await API.setLayout(layout);
        } catch (e) {
            console.error('Failed to save layout:', e);
        }
    }

    applyLayout(layout) {
        const container = document.getElementById('today-view');
        if (!container) return;

        const sorted = layout.sort((a, b) => a.sort_order - b.sort_order);
        for (const item of sorted) {
            const card = container.querySelector(`[data-card-id="${item.card_id}"]`);
            if (card) {
                container.appendChild(card);
                if (!item.visible) card.style.display = 'none';
            }
        }
    }
}

let layoutManager;

function initLayout() {
    layoutManager = new LayoutManager();
    layoutManager.init();
}
