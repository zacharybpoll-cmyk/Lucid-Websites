/**
 * Grove — SVG tree forest rendering
 * Each day grows a tree. Missed days wilt. Rainfall revives.
 */

class GroveRenderer {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.data = null;
    }

    async load() {
        try {
            this.data = await API.getGrove();
            this.render();
        } catch (e) {
            console.error('Failed to load grove:', e);
        }
    }

    render() {
        if (!this.container || !this.data) return;

        const { trees, rainfall, wilted_count, growing_count } = this.data;

        // Header
        let html = `
            <div class="grove-header">
                <div class="grove-stats">
                    <span class="grove-stat-item"><span class="grove-tree-icon">&#127794;</span> ${growing_count} growing</span>
                    ${wilted_count > 0 ? `<span class="grove-stat-item grove-wilted-stat"><span class="grove-wilted-icon">&#127811;</span> ${wilted_count} wilted</span>` : ''}
                </div>
                <div class="grove-rainfall">
                    <span class="rainfall-icon">&#127783;</span>
                    <span class="rainfall-count">${rainfall}</span>
                </div>
            </div>
        `;

        // Tree grid (show last 30 trees)
        const displayTrees = trees.slice(0, 30).reverse(); // oldest first
        html += '<div class="grove-forest">';

        for (const tree of displayTrees) {
            const isWilted = tree.tree_state === 'wilted';
            const stage = tree.growth_stage || 1;
            const cls = isWilted ? 'grove-tree wilted' : `grove-tree stage-${stage}`;
            const dateLabel = new Date(tree.date + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

            html += `<div class="${cls}" data-date="${tree.date}" title="${dateLabel}: ${isWilted ? 'Wilted' : 'Stage ' + stage}">`;
            html += this._renderTreeSVG(stage, isWilted, tree.revived);
            html += `<span class="grove-tree-date">${dateLabel}</span>`;
            if (isWilted && rainfall > 0) {
                html += `<button class="grove-revive-btn" onclick="reviveGroveTree('${tree.date}')" title="Use rainfall to revive">&#127783;</button>`;
            }
            html += '</div>';
        }

        html += '</div>';

        this.container.innerHTML = html;
    }

    _renderTreeSVG(stage, isWilted, revived) {
        const color = isWilted ? '#9a9a9a' : (revived ? '#7ab88e' : '#5a9a6e');
        const trunkColor = isWilted ? '#8a7a6a' : '#8b6914';

        if (stage <= 1) {
            // Seedling
            return `<svg viewBox="0 0 40 50" class="tree-svg">
                <line x1="20" y1="45" x2="20" y2="30" stroke="${trunkColor}" stroke-width="2"/>
                <circle cx="20" cy="26" r="6" fill="${color}" opacity="0.8"/>
            </svg>`;
        } else if (stage === 2) {
            // Growing
            return `<svg viewBox="0 0 40 50" class="tree-svg">
                <line x1="20" y1="45" x2="20" y2="22" stroke="${trunkColor}" stroke-width="3"/>
                <circle cx="20" cy="18" r="10" fill="${color}" opacity="0.85"/>
                <circle cx="14" cy="22" r="6" fill="${color}" opacity="0.7"/>
                <circle cx="26" cy="22" r="6" fill="${color}" opacity="0.7"/>
            </svg>`;
        } else if (stage === 3) {
            // Blooming
            return `<svg viewBox="0 0 40 50" class="tree-svg">
                <line x1="20" y1="45" x2="20" y2="18" stroke="${trunkColor}" stroke-width="3.5"/>
                <line x1="20" y1="28" x2="12" y2="22" stroke="${trunkColor}" stroke-width="2"/>
                <line x1="20" y1="28" x2="28" y2="22" stroke="${trunkColor}" stroke-width="2"/>
                <circle cx="20" cy="14" r="11" fill="${color}" opacity="0.9"/>
                <circle cx="12" cy="19" r="7" fill="${color}" opacity="0.8"/>
                <circle cx="28" cy="19" r="7" fill="${color}" opacity="0.8"/>
            </svg>`;
        } else {
            // Full canopy (stage 4)
            return `<svg viewBox="0 0 40 50" class="tree-svg">
                <line x1="20" y1="45" x2="20" y2="15" stroke="${trunkColor}" stroke-width="4"/>
                <line x1="20" y1="30" x2="10" y2="20" stroke="${trunkColor}" stroke-width="2.5"/>
                <line x1="20" y1="30" x2="30" y2="20" stroke="${trunkColor}" stroke-width="2.5"/>
                <line x1="20" y1="24" x2="14" y2="16" stroke="${trunkColor}" stroke-width="2"/>
                <line x1="20" y1="24" x2="26" y2="16" stroke="${trunkColor}" stroke-width="2"/>
                <circle cx="20" cy="11" r="12" fill="${color}"/>
                <circle cx="10" cy="17" r="8" fill="${color}" opacity="0.9"/>
                <circle cx="30" cy="17" r="8" fill="${color}" opacity="0.9"/>
                <circle cx="14" cy="12" r="6" fill="${color}" opacity="0.8"/>
                <circle cx="26" cy="12" r="6" fill="${color}" opacity="0.8"/>
            </svg>`;
        }
    }
}

let groveRenderer;

function initGrove() {
    groveRenderer = new GroveRenderer('grove-container');
}

async function updateGrove() {
    if (groveRenderer) await groveRenderer.load();
}

async function reviveGroveTree(dateStr) {
    try {
        const result = await API.reviveTree(dateStr);
        if (result.success) {
            triggerSanctuary('revive', 'Tree revived! Your grove is healing.');
            await updateGrove();
        }
    } catch (e) {
        console.error('Failed to revive tree:', e);
    }
}
